"""构造工资修正特征表 wage_fix_v4。

v4 在 v3 基础上完成最后一块：低值段（月薪<1000元）里的日薪、时薪换算为月薪。
判定顺序：①极小值置缺失；②文本写“元/小时”按×174；③文本写“元/天”按×21.75；
④2021年平台28按×12（纠正被误÷12）；⑤其余无文本证据的，<60元按×174、60元以上按×21.75。
换算后仍超过10万元的置为缺失（本数据中理论上不会发生，作为保险）。

不修改 cleaned_v1、confirmed_core_v2 以及 wage_fix_v1/v2/v3。
输出：<features_root>/wage_fix_v4/jobs_{year}_wage_fix.parquet
      <features_root>/wage_fix_v4/manifest.json
      outputs/qc/wage_fix_v4_summary.csv
      outputs/qc/wage_fix_v4_distribution.csv
      outputs/qc/wage_fix_v4_low_tail_resolved.csv
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v4.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "wage_fix_v4_summary.csv"
DIST_PATH = QC_ROOT / "wage_fix_v4_distribution.csv"
RESOLVED_PATH = QC_ROOT / "wage_fix_v4_low_tail_resolved.csv"

YEARS = tuple(range(2018, 2026))
FEATURE_VERSION = "wage_fix_v4"
BASE_VERSION = "wage_fix_v3"
EXPECTED_ROWS = 5_235_461
LOW_THRESHOLD = 1000.0
TINY_THRESHOLD = 10.0
HOURLY_CUT = 60.0
DAILY_MULT = 21.75
HOURLY_MULT = 174.0
DIV12_MULT = 12.0
CAP = 100_000.0
EXPECTED_LOW = 10_649
EXPECTED_TINY = 261

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("wage_mid_orig", pa.float64(), nullable=False),
        pa.field("ln_wage_orig", pa.float64(), nullable=False),
        pa.field("wage_mid_fixed", pa.float64(), nullable=True),
        pa.field("ln_wage_fixed", pa.float64(), nullable=True),
        pa.field("wage_fix_flag", pa.int8(), nullable=False),
        pa.field("wage_fix_rule", pa.string()),
        pa.field("wage_fix_factor", pa.float64(), nullable=False),
        pa.field("wage_fix_action", pa.string(), nullable=False),
        pa.field("wage_fix_version", pa.string(), nullable=False),
    ]
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or list(rows[0])
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    rules = load_json(RULES_PATH)
    cleaned_root = Path(storage["curated_root"]) / "cleaned_v1"
    base_root = Path(storage["features_root"]) / BASE_VERSION
    output_root = Path(storage["features_root"]) / FEATURE_VERSION
    output_root.mkdir(parents=True, exist_ok=True)

    rule_by_id = {r["rule_id"]: r for r in rules["low_tail_rules"]}
    counts = {rid: 0 for rid in rule_by_id}
    counts["missing_over_cap"] = 0
    summary_rows: list[dict] = []
    resolved_rows: list[dict] = []
    total_rows = 0
    total_low = 0

    for year in YEARS:
        base = pd.read_parquet(base_root / f"jobs_{year}_wage_fix.parquet")
        source = pd.read_parquet(
            cleaned_root / f"jobs_{year}_cleaned.parquet",
            columns=["来源记录ID", "来源", "招聘岗位", "职位描述"],
        )
        df = base.merge(
            source, left_on="source_record_id", right_on="来源记录ID", how="left", validate="one_to_one"
        )
        if len(df) != len(base):
            raise RuntimeError(f"{year}年连接后行数变化")

        wage = df["wage_mid_fixed"].to_numpy(dtype="float64", na_value=np.nan).copy()
        ln = df["ln_wage_fixed"].to_numpy(dtype="float64", na_value=np.nan).copy()
        flag = df["wage_fix_flag"].to_numpy(dtype="int8").copy()
        factor = df["wage_fix_factor"].to_numpy(dtype="float64").copy()
        rule_names = df["wage_fix_rule"].fillna("").astype(object).to_numpy().copy()
        action = np.where(flag == 2, "set_missing", np.where(flag == 1, "divide", "none")).astype(object)
        action[flag == 0] = "none"

        text = df["职位描述"].fillna("").astype(str).to_numpy()
        platform = df["来源"].fillna("").astype(str).to_numpy()

        low = np.nan_to_num(wage, nan=1e9) < LOW_THRESHOLD
        hourly_text = np.array(["元/小时" in t or "每小时" in t for t in text])
        daily_text = np.array(["元/天" in t or "元一天" in t for t in text])
        is_p28_2021 = (platform == "平台28") & (year == 2021)

        new_wage = np.full(len(df), np.nan, dtype="float64")
        new_rule = np.full(len(df), "", dtype=object)
        new_mult = np.ones(len(df), dtype="float64")
        new_flag = np.zeros(len(df), dtype="int8")

        # ① 极小值 → 缺失
        m = low & (wage <= TINY_THRESHOLD)
        new_rule[m] = "missing_tiny_value"
        new_flag[m] = 2
        counts["missing_tiny_value"] += int(m.sum())

        # ② 文本写时薪
        m2 = low & ~m & hourly_text
        new_wage[m2] = wage[m2] * HOURLY_MULT
        new_mult[m2] = HOURLY_MULT
        new_rule[m2] = "hourly_to_monthly"
        counts["hourly_to_monthly"] += int(m2.sum())

        # ③ 文本写日薪
        m3 = low & ~m & ~m2 & daily_text
        new_wage[m3] = wage[m3] * DAILY_MULT
        new_mult[m3] = DAILY_MULT
        new_rule[m3] = "daily_to_monthly_by_text"
        counts["daily_to_monthly_by_text"] += int(m3.sum())

        # ④ 低于60元且无单位文本：按小时（11—59元不可能是月薪，也不可能是日薪）
        m5 = low & ~m & ~m2 & ~m3 & (wage < HOURLY_CUT)
        new_wage[m5] = wage[m5] * HOURLY_MULT
        new_mult[m5] = HOURLY_MULT
        new_rule[m5] = "hourly_to_monthly_by_magnitude"
        counts["hourly_to_monthly_by_magnitude"] += int(m5.sum())

        # ⑤ 2021平台28 被误÷12
        m4 = low & ~m & ~m2 & ~m3 & ~m5 & is_p28_2021
        new_wage[m4] = wage[m4] * DIV12_MULT
        new_mult[m4] = DIV12_MULT
        new_rule[m4] = "error_div12_to_monthly"
        counts["error_div12_to_monthly"] += int(m4.sum())

        m6 = low & ~m & ~m2 & ~m3 & ~m5 & ~m4
        new_wage[m6] = wage[m6] * DAILY_MULT
        new_mult[m6] = DAILY_MULT
        new_rule[m6] = "daily_to_monthly_by_magnitude"
        counts["daily_to_monthly_by_magnitude"] += int(m6.sum())

        # 保险：换算后超过10万的置缺失
        over = low & ~m & (new_wage > CAP)
        if over.any():
            new_wage[over] = np.nan
            new_rule[over] = "missing_over_cap"
            new_flag[over] = 2
            counts["missing_over_cap"] += int(over.sum())

        touched = low
        new_flag[touched] = np.where(
            (new_rule[touched] == "missing_tiny_value") | (new_rule[touched] == "missing_over_cap"), 2, 1
        )

        # 汇总到最终列：低值段用新值，其余沿用v3
        out_wage = wage.copy()
        out_ln = ln.copy()
        out_mult = factor.copy()
        out_rule = rule_names.copy()
        out_flag = flag.copy()
        out_action = action.copy()

        out_wage[touched] = np.where(new_flag[touched] == 2, np.nan, new_wage[touched])
        out_flag[touched] = new_flag[touched]
        out_rule[touched] = new_rule[touched]
        out_mult[touched] = new_mult[touched]
        out_action[touched] = np.where(new_flag[touched] == 2, "set_missing", "multiply")
        finite = ~np.isnan(out_wage)
        out_ln = np.where(finite, np.log(np.where(finite, out_wage, 1.0)), np.nan)

        if np.nanmax(np.nan_to_num(out_wage, nan=0.0)) > CAP:
            raise RuntimeError(f"{year}年处理后仍存在月薪>10万")

        table = pa.Table.from_arrays(
            [
                pa.array(df["source_record_id"].to_numpy(), type=pa.string()),
                pa.array(df["wage_mid_orig"].to_numpy(), type=pa.float64()),
                pa.array(df["ln_wage_orig"].to_numpy(), type=pa.float64()),
                pa.array(out_wage, type=pa.float64(), mask=np.isnan(out_wage)),
                pa.array(out_ln, type=pa.float64(), mask=np.isnan(out_ln)),
                pa.array(out_flag, type=pa.int8()),
                pa.array(out_rule, type=pa.string()),
                pa.array(out_mult, type=pa.float64()),
                pa.array(out_action, type=pa.string()),
                pa.array(np.full(len(df), FEATURE_VERSION, dtype=object), type=pa.string()),
            ],
            schema=OUTPUT_SCHEMA,
        )
        tmp = (output_root / f"jobs_{year}_wage_fix.parquet").with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        check = pq.ParquetFile(tmp)
        if check.metadata.num_rows != len(df):
            raise RuntimeError(f"{year}年输出行数异常")
        check.close()
        os.replace(tmp, output_root / f"jobs_{year}_wage_fix.parquet")

        for idx in np.where(touched)[0]:
            resolved_rows.append(
                {
                    "source_record_id": df["source_record_id"].iloc[idx],
                    "year": year,
                    "platform": platform[idx],
                    "job_title": str(df["招聘岗位"].iloc[idx])[:40],
                    "wage_before": round(float(wage[idx]), 2),
                    "wage_after": "" if np.isnan(out_wage[idx]) else round(float(out_wage[idx]), 2),
                    "rule": out_rule[idx],
                    "factor": round(float(out_mult[idx]), 2),
                }
            )

        low_n = int(low.sum())
        total_low += low_n
        total_rows += len(df)
        summary_rows.append(
            {
                "year": year,
                "rows": len(df),
                "low_tail_rows": low_n,
                "converted": int(((out_flag == 1) & touched).sum()),
                "set_missing": int(((out_flag == 2) & touched).sum()),
                "flag1_total": int((out_flag == 1).sum()),
                "flag2_total": int((out_flag == 2).sum()),
                "output_path": str(output_root / f"jobs_{year}_wage_fix.parquet"),
            }
        )
        print(f"{year}: rows={len(df):,} low={low_n:,} converted={int(((out_flag==1)&touched).sum()):,} "
              f"missing={int(((out_flag==2)&touched).sum()):,}", flush=True)

    if total_rows != EXPECTED_ROWS:
        raise RuntimeError(f"总行数异常：{total_rows:,}")
    if total_low != EXPECTED_LOW:
        raise RuntimeError(f"低值段条数异常：{total_low:,}")
    if counts["missing_tiny_value"] != EXPECTED_TINY:
        raise RuntimeError(f"极小值条数异常：{counts['missing_tiny_value']:,}")

    summary_rows.append(
        {
            "year": "合计",
            "rows": total_rows,
            "low_tail_rows": total_low,
            "converted": sum(r["converted"] for r in summary_rows),
            "set_missing": sum(r["set_missing"] for r in summary_rows),
            "flag1_total": sum(r["flag1_total"] for r in summary_rows),
            "flag2_total": sum(r["flag2_total"] for r in summary_rows),
            "output_path": str(output_root),
        }
    )
    write_csv(SUMMARY_PATH, summary_rows)
    write_csv(RESOLVED_PATH, resolved_rows)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    glob = str(output_root / "jobs_*_wage_fix.parquet").replace("\\", "/")
    year_expr = "regexp_extract(filename, 'jobs_([0-9]{4})_', 1)"
    rows = con.execute(
        f"""
        SELECT {year_expr} AS yr, count(*), count(wage_mid_fixed),
               sum(CASE WHEN wage_fix_flag=1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag=2 THEN 1 ELSE 0 END),
               round(avg(wage_mid_fixed),2), round(median(wage_mid_fixed),2),
               round(quantile_cont(wage_mid_fixed,0.01),2), round(quantile_cont(wage_mid_fixed,0.99),2),
               round(max(wage_mid_fixed),2), round(stddev_samp(wage_mid_fixed),2)
        FROM read_parquet('{glob}', filename=true) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    dist_rows = [
        {
            "year": int(r[0]), "rows": int(r[1]), "valid_rows": int(r[2]), "corrected": int(r[3]),
            "missing": int(r[4]), "mean_wage": round(float(r[5]), 2), "median_wage": round(float(r[6]), 2),
            "p1_wage": round(float(r[7]), 2), "p99_wage": round(float(r[8]), 2),
            "max_wage": round(float(r[9]), 2), "sd_wage": round(float(r[10]), 2),
        }
        for r in rows
    ]
    t = con.execute(
        f"""
        SELECT count(*), count(wage_mid_fixed),
               sum(CASE WHEN wage_fix_flag=1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag=2 THEN 1 ELSE 0 END),
               round(avg(wage_mid_fixed),2), round(median(wage_mid_fixed),2),
               round(quantile_cont(wage_mid_fixed,0.01),2), round(quantile_cont(wage_mid_fixed,0.99),2),
               round(max(wage_mid_fixed),2), round(stddev_samp(wage_mid_fixed),2),
               round(skewness(ln_wage_fixed),3), round(kurtosis(ln_wage_fixed),3),
               count(*) FILTER (WHERE wage_mid_fixed < 1000)
        FROM read_parquet('{glob}')
        """
    ).fetchone()
    dist_rows.append(
        {
            "year": "合计", "rows": int(t[0]), "valid_rows": int(t[1]), "corrected": int(t[2]),
            "missing": int(t[3]), "mean_wage": round(float(t[4]), 2), "median_wage": round(float(t[5]), 2),
            "p1_wage": round(float(t[6]), 2), "p99_wage": round(float(t[7]), 2),
            "max_wage": round(float(t[8]), 2), "sd_wage": round(float(t[9]), 2),
        }
    )
    write_csv(DIST_PATH, dist_rows)

    manifest = {
        "version": FEATURE_VERSION,
        "base_version": BASE_VERSION,
        "input_version": "cleaned_v1",
        "approved_by": rules.get("approved_by"),
        "rows": total_rows,
        "valid_rows": dist_rows[-1]["valid_rows"],
        "corrected_total": dist_rows[-1]["corrected"],
        "missing_total": dist_rows[-1]["missing"],
        "low_tail_rows": total_low,
        "low_tail_rule_counts": counts,
        "conversion_basis": rules["conversion_basis"],
        "rules_file": str(RULES_PATH),
        "low_tail_rules": rules["low_tail_rules"],
        "join_key": "source_record_id",
        "flag_definition": {"0": "未修正", "1": "已修正（÷12/÷10 或 换算为月薪）", "2": "置为缺失"},
        "action_definition": {"none": "未修正", "divide": "除以12或10", "multiply": "乘以21.75/174/12", "set_missing": "置为缺失"},
        "ln_wage_skew": round(float(t[10]), 3),
        "ln_wage_kurtosis": round(float(t[11]), 3),
        "remaining_below_1000": int(t[12]),
        "summary_file": str(SUMMARY_PATH),
        "distribution_file": str(DIST_PATH),
        "low_tail_resolved_file": str(RESOLVED_PATH),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"WAGE_FIX_V4_OUTPUT={output_root}")
    converted_total = sum(r["converted"] for r in summary_rows[:-1])
    missing_total = sum(r["set_missing"] for r in summary_rows[:-1])
    print(f"LOW_TAIL={total_low:,} 换算={converted_total:,} "
          f"缺失={missing_total:,}")
    print(f"LN_SKEW={manifest['ln_wage_skew']} LN_KURT={manifest['ln_wage_kurtosis']}")
    print("WAGE_FIX_V4_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



