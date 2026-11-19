"""构造工资修正特征表 wage_fix_v3。

v3 在 v2 基础上解决“修正后仍超过10万”的记录：
1. 未修正过、且月薪<=120万的，按年薪÷12（2,896条）；
2. 明显无法修正的置为缺失（86条）：
   - 13条未修正但原值>120万，÷12后仍超10万；
   - 73条已被 v1 按年薪÷12过一次、原值280万—800万，再除一次缺乏依据。
处理完成后全表不存在月薪>100,000的记录。

不修改 cleaned_v1、confirmed_core_v2、wage_fix_v1、wage_fix_v2。
输出：<features_root>/wage_fix_v3/jobs_{year}_wage_fix.parquet
      <features_root>/wage_fix_v3/manifest.json
      outputs/qc/wage_fix_v3_summary.csv
      outputs/qc/wage_fix_v3_distribution.csv
      outputs/qc/wage_fix_v3_extremes_resolved.csv
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
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v3.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "wage_fix_v3_summary.csv"
DIST_PATH = QC_ROOT / "wage_fix_v3_distribution.csv"
RESOLVED_PATH = QC_ROOT / "wage_fix_v3_extremes_resolved.csv"

YEARS = tuple(range(2018, 2026))
FEATURE_VERSION = "wage_fix_v3"
BASE_VERSION = "wage_fix_v2"
EXPECTED_ROWS = 5_235_461
EXTREME_THRESHOLD = 100_000.0
UNFIXABLE_CAP = 1_200_000.0
EXPECTED_FIXED = 2_896
EXPECTED_MISSING = 86

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
    divide_rule = next(r for r in rules["extreme_rules"] if r["action"] == "divide")
    missing_rule = next(r for r in rules["extreme_rules"] if r["action"] == "set_missing")
    base_root = Path(storage["features_root"]) / BASE_VERSION
    output_root = Path(storage["features_root"]) / FEATURE_VERSION
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    resolved_rows: list[dict] = []
    totals = {"fix": 0, "miss": 0}

    for year in YEARS:
        base_path = base_root / f"jobs_{year}_wage_fix.parquet"
        output_path = output_root / f"jobs_{year}_wage_fix.parquet"
        temp_path = output_path.with_suffix(".parquet.tmp")

        frame = pd.read_parquet(base_path)
        wage = frame["wage_mid_fixed"].to_numpy(dtype="float64", na_value=np.nan)
        ln = frame["ln_wage_fixed"].to_numpy(dtype="float64", na_value=np.nan)
        flag = frame["wage_fix_flag"].to_numpy(dtype="int8").copy()
        rule_names = frame["wage_fix_rule"].fillna("").astype(object).to_numpy().copy()

        over = np.nan_to_num(wage, nan=-1.0) > EXTREME_THRESHOLD
        fixable = over & (flag == 0) & (wage <= UNFIXABLE_CAP)
        unfixable = over & ~fixable

        wage_out = wage.copy()
        ln_out = ln.copy()
        wage_out[fixable] = wage[fixable] / 12.0
        ln_out[fixable] = np.log(wage_out[fixable])
        flag[fixable] = 1
        rule_names[fixable] = divide_rule["rule_id"]

        wage_out[unfixable] = np.nan
        ln_out[unfixable] = np.nan
        flag[unfixable] = 2
        rule_names[unfixable] = missing_rule["rule_id"]

        factors = frame["wage_fix_factor"].to_numpy(dtype="float64").copy()
        factors[fixable] = 12.0

        if np.nanmax(np.nan_to_num(wage_out, nan=0.0)) > EXTREME_THRESHOLD:
            raise RuntimeError(f"{year}年处理后仍存在月薪>10万")

        table = pa.Table.from_arrays(
            [
                pa.array(frame["source_record_id"].to_numpy(), type=pa.string()),
                pa.array(frame["wage_mid_orig"].to_numpy(), type=pa.float64()),
                pa.array(frame["ln_wage_orig"].to_numpy(), type=pa.float64()),
                pa.array(wage_out, type=pa.float64(), mask=np.isnan(wage_out)),
                pa.array(ln_out, type=pa.float64(), mask=np.isnan(ln_out)),
                pa.array(flag, type=pa.int8()),
                pa.array(rule_names, type=pa.string()),
                pa.array(factors, type=pa.float64()),
                pa.array(np.full(len(frame), FEATURE_VERSION, dtype=object), type=pa.string()),
            ],
            schema=OUTPUT_SCHEMA,
        )
        pq.write_table(table, temp_path, compression="zstd")
        check = pq.ParquetFile(temp_path)
        if check.metadata.num_rows != len(frame):
            raise RuntimeError(f"{year}年输出行数异常")
        check.close()
        os.replace(temp_path, output_path)

        for idx in np.where(over)[0]:
            resolved_rows.append(
                {
                    "source_record_id": frame["source_record_id"].iloc[idx],
                    "year": year,
                    "wage_before_v3": round(float(wage[idx]), 2),
                    "wage_after_v3": "" if np.isnan(wage_out[idx]) else round(float(wage_out[idx]), 2),
                    "v2_flag": int(frame["wage_fix_flag"].iloc[idx]),
                    "v3_flag": int(flag[idx]),
                    "v3_rule": divide_rule["rule_id"] if fixable[idx] else missing_rule["rule_id"],
                }
            )

        totals["fix"] += int(fixable.sum())
        totals["miss"] += int(unfixable.sum())
        summary_rows.append(
            {
                "year": year,
                "rows": len(frame),
                "flag0_unchanged": int((flag == 0).sum()),
                "flag1_corrected": int((flag == 1).sum()),
                "flag2_missing": int((flag == 2).sum()),
                "v3_divided": int(fixable.sum()),
                "v3_missing": int(unfixable.sum()),
                "output_path": str(output_path),
            }
        )
        print(
            f"{year}: rows={len(frame):,} v3÷12={int(fixable.sum()):,} v3缺失={int(unfixable.sum()):,} "
            f"合计缺失={int((flag == 2).sum()):,}",
            flush=True,
        )

    if totals["fix"] != EXPECTED_FIXED or totals["miss"] != EXPECTED_MISSING:
        raise RuntimeError(f"处理条数异常：fix={totals['fix']:,} miss={totals['miss']:,}")
    if sum(r["rows"] for r in summary_rows) != EXPECTED_ROWS:
        raise RuntimeError("总行数异常")

    summary_rows.append(
        {
            "year": "合计",
            "rows": sum(r["rows"] for r in summary_rows),
            "flag0_unchanged": sum(r["flag0_unchanged"] for r in summary_rows),
            "flag1_corrected": sum(r["flag1_corrected"] for r in summary_rows),
            "flag2_missing": sum(r["flag2_missing"] for r in summary_rows),
            "v3_divided": totals["fix"],
            "v3_missing": totals["miss"],
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
        SELECT {year_expr} AS yr, count(*),
               sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag = 2 THEN 1 ELSE 0 END),
               count(wage_mid_fixed), round(avg(wage_mid_fixed), 2), round(median(wage_mid_fixed), 2),
               round(quantile_cont(wage_mid_fixed, 0.99), 2), round(max(wage_mid_fixed), 2),
               round(avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END), 6)
        FROM read_parquet('{glob}', filename=true) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    dist_rows = [
        {
            "year": int(r[0]), "rows": int(r[1]), "corrected": int(r[2]), "missing": int(r[3]),
            "valid_rows": int(r[4]), "mean_wage": round(float(r[5]), 2), "median_wage": round(float(r[6]), 2),
            "p99_wage": round(float(r[7]), 2), "max_wage": round(float(r[8]), 2),
            "share_over_100k": round(float(r[9]), 6),
        }
        for r in rows
    ]
    t = con.execute(
        f"""
        SELECT count(*), count(wage_mid_fixed), avg(wage_mid_fixed), median(wage_mid_fixed),
               quantile_cont(wage_mid_fixed, 0.99), max(wage_mid_fixed),
               avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag = 2 THEN 1 ELSE 0 END)
        FROM read_parquet('{glob}')
        """
    ).fetchone()
    dist_rows.append(
        {
            "year": "合计", "rows": int(t[0]), "corrected": int(t[7]), "missing": int(t[8]),
            "valid_rows": int(t[1]), "mean_wage": round(float(t[2]), 2), "median_wage": round(float(t[3]), 2),
            "p99_wage": round(float(t[4]), 2), "max_wage": round(float(t[5]), 2),
            "share_over_100k": round(float(t[6]), 6),
        }
    )
    write_csv(DIST_PATH, dist_rows)

    manifest = {
        "version": FEATURE_VERSION,
        "base_version": BASE_VERSION,
        "input_version": "cleaned_v1",
        "rows": EXPECTED_ROWS,
        "valid_rows": dist_rows[-1]["valid_rows"],
        "extreme_divided": totals["fix"],
        "extreme_missing": totals["miss"],
        "rules_file": str(RULES_PATH),
        "extreme_rules": rules["extreme_rules"],
        "target_invariant": rules["target_invariant"],
        "join_key": "source_record_id",
        "flag_definition": {"0": "未修正", "1": "已修正（÷12或÷10）", "2": "置为缺失"},
        "usage": "工资与对数工资用 wage_mid_fixed / ln_wage_fixed；flag=2 表示缺失",
        "summary_file": str(SUMMARY_PATH),
        "distribution_file": str(DIST_PATH),
        "extremes_resolved_file": str(RESOLVED_PATH),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"WAGE_FIX_V3_OUTPUT={output_root}")
    print(f"WAGE_FIX_V3_DIVIDED={totals['fix']:,} MISSING={totals['miss']:,}")
    print("WAGE_FIX_V3_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
