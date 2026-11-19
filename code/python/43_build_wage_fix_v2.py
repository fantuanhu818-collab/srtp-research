"""构造工资修正特征表 wage_fix_v2。

v2 = v1 的三组年薪/量级修正 + “面议”占位值置缺失。
2018年平台38有46条广告的最低月薪和最高月薪都填成 888888（“发发发”吉利数），
是平台表示“薪资面议”的占位值，不是任何真实工资。v2 把这些记录置为缺失，
并用 wage_fix_flag=2 标记，既保留原值痕迹，又不让假数字进入均值和回归。

不修改 cleaned_v1、confirmed_core_v2 和 wage_fix_v1。
输出：<features_root>/wage_fix_v2/jobs_{year}_wage_fix.parquet
      <features_root>/wage_fix_v2/manifest.json
      outputs/qc/wage_fix_v2_summary.csv
      outputs/qc/wage_fix_v2_distribution.csv
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
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v2.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "wage_fix_v2_summary.csv"
DIST_PATH = QC_ROOT / "wage_fix_v2_distribution.csv"

YEARS = tuple(range(2018, 2026))
FEATURE_VERSION = "wage_fix_v2"
BASE_VERSION = "wage_fix_v1"
EXPECTED_ROWS = 5_235_461
EXPECTED_DIVIDED = 135_930
EXPECTED_MISSING = 46
PLACEHOLDER_VALUE = 888_888.0
EXTREME_THRESHOLD = 100_000.0

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
    cleaned_root = Path(storage["curated_root"]) / "cleaned_v1"
    base_root = Path(storage["features_root"]) / BASE_VERSION
    output_root = Path(storage["features_root"]) / FEATURE_VERSION
    output_root.mkdir(parents=True, exist_ok=True)

    placeholder_rule = rules["placeholder_rules"][0]
    rule_id = placeholder_rule["rule_id"]
    value = float(placeholder_rule["condition"]["value"])

    summary_rows: list[dict] = []
    total = {"rows": 0, "divided": 0, "missing": 0}

    for year in YEARS:
        base_path = base_root / f"jobs_{year}_wage_fix.parquet"
        cleaned_path = cleaned_root / f"jobs_{year}_cleaned.parquet"
        output_path = output_root / f"jobs_{year}_wage_fix.parquet"
        temp_path = output_path.with_suffix(".parquet.tmp")

        base = pd.read_parquet(base_path)
        source = pd.read_parquet(cleaned_path, columns=["来源记录ID", "最低月薪", "最高月薪"])
        merged = base.merge(
            source, left_on="source_record_id", right_on="来源记录ID", how="left", validate="one_to_one"
        )
        if len(merged) != len(base):
            raise RuntimeError(f"{year}年与清洗数据连接后行数变化")

        # 单端缺失是清洗阶段允许的正常形态（只有一个工资端点有效），不视为异常。
        # 占位值只认“两个端点同时等于888888”，缺一端的不算。
        low = merged["最低月薪"].to_numpy(dtype="float64", na_value=np.nan)
        high = merged["最高月薪"].to_numpy(dtype="float64", na_value=np.nan)
        placeholder = (low == value) & (high == value)
        fixed = merged["wage_mid_fixed"].to_numpy(dtype="float64", na_value=np.nan).copy()
        ln_fixed = merged["ln_wage_fixed"].to_numpy(dtype="float64", na_value=np.nan).copy()
        flag = merged["wage_fix_flag"].to_numpy(dtype="int8").copy()
        rule_names = merged["wage_fix_rule"].fillna("").astype(object).to_numpy().copy()

        fixed[placeholder] = np.nan
        ln_fixed[placeholder] = np.nan
        flag[placeholder] = 2
        rule_names[placeholder] = rule_id

        if not np.isfinite(fixed[~placeholder]).all():
            raise RuntimeError(f"{year}年非占位记录存在无效修正工资")

        table = pa.Table.from_arrays(
            [
                pa.array(merged["source_record_id"].to_numpy(), type=pa.string()),
                pa.array(merged["wage_mid_orig"].to_numpy(), type=pa.float64()),
                pa.array(merged["ln_wage_orig"].to_numpy(), type=pa.float64()),
                # float64 里的 NaN 在 Parquet 中仍是“有效值”，必须用 mask 明确写成 NULL
                pa.array(fixed, type=pa.float64(), mask=np.isnan(fixed)),
                pa.array(ln_fixed, type=pa.float64(), mask=np.isnan(ln_fixed)),
                pa.array(flag, type=pa.int8()),
                pa.array(rule_names, type=pa.string()),
                pa.array(merged["wage_fix_factor"].to_numpy(), type=pa.float64()),
                pa.array(np.full(len(merged), FEATURE_VERSION, dtype=object), type=pa.string()),
            ],
            schema=OUTPUT_SCHEMA,
        )
        pq.write_table(table, temp_path, compression="zstd")
        check = pq.ParquetFile(temp_path)
        if check.metadata.num_rows != len(merged):
            raise RuntimeError(f"{year}年输出行数异常")
        check.close()
        os.replace(temp_path, output_path)

        missing_count = int(placeholder.sum())
        divided_count = int((flag == 1).sum())
        total["rows"] += len(merged)
        total["divided"] += divided_count
        total["missing"] += missing_count
        summary_rows.append(
            {
                "year": year,
                "rows": len(merged),
                "unchanged": int((flag == 0).sum()),
                "divided": divided_count,
                "set_missing": missing_count,
                "output_path": str(output_path),
            }
        )
        print(f"{year}: rows={len(merged):,} divided={divided_count:,} missing={missing_count}", flush=True)

    if total["rows"] != EXPECTED_ROWS:
        raise RuntimeError(f"总行数异常：{total['rows']:,}")
    if total["divided"] != EXPECTED_DIVIDED:
        raise RuntimeError(f"修正条数异常：{total['divided']:,}")
    if total["missing"] != EXPECTED_MISSING:
        raise RuntimeError(f"缺失条数异常：{total['missing']:,}")

    summary_rows.append(
        {
            "year": "合计",
            "rows": total["rows"],
            "unchanged": total["rows"] - total["divided"] - total["missing"],
            "divided": total["divided"],
            "set_missing": total["missing"],
            "output_path": str(output_root),
        }
    )
    write_csv(SUMMARY_PATH, summary_rows)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    glob = str(output_root / "jobs_*_wage_fix.parquet").replace("\\", "/")
    year_expr = "regexp_extract(filename, 'jobs_([0-9]{4})_', 1)"
    rows = con.execute(
        f"""
        SELECT {year_expr} AS yr,
               count(*) AS rows,
               sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END) AS divided,
               sum(CASE WHEN wage_fix_flag = 2 THEN 1 ELSE 0 END) AS missing,
               count(wage_mid_fixed) AS valid_rows,
               avg(wage_mid_fixed) AS mean_after,
               median(wage_mid_fixed) AS median_after,
               quantile_cont(wage_mid_fixed, 0.99) AS p99_after,
               max(wage_mid_fixed) AS max_after,
               avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END) AS share_over_100k
        FROM read_parquet('{glob}', filename=true)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    dist_rows = [
        {
            "year": int(r[0]), "rows": int(r[1]), "divided": int(r[2]), "set_missing": int(r[3]),
            "valid_rows": int(r[4]),
            "mean_wage": round(float(r[5]), 2), "median_wage": round(float(r[6]), 2),
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
            "year": "合计", "rows": int(t[0]), "divided": int(t[7]), "set_missing": int(t[8]),
            "valid_rows": int(t[1]),
            "mean_wage": round(float(t[2]), 2), "median_wage": round(float(t[3]), 2),
            "p99_wage": round(float(t[4]), 2), "max_wage": round(float(t[5]), 2),
            "share_over_100k": round(float(t[6]), 6),
        }
    )
    write_csv(DIST_PATH, dist_rows)

    manifest = {
        "version": FEATURE_VERSION,
        "base_version": BASE_VERSION,
        "input_version": "cleaned_v1",
        "rows": total["rows"],
        "valid_rows": total["rows"] - total["missing"],
        "divided_rows": total["divided"],
        "set_missing_rows": total["missing"],
        "join_key": "source_record_id",
        "rules_file": str(RULES_PATH),
        "placeholder_rules": rules["placeholder_rules"],
        "flag_definition": rules["wage_fix_flag_definition"],
        "created_variables": OUTPUT_SCHEMA.names[1:],
        "usage": "工资与对数工资用 wage_mid_fixed / ln_wage_fixed；wage_fix_flag=2 表示该条为占位值、工资缺失；缺失去向已在回归样本中自然剔除",
        "summary_file": str(SUMMARY_PATH),
        "distribution_file": str(DIST_PATH),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"WAGE_FIX_V2_OUTPUT={output_root}")
    print(f"WAGE_FIX_V2_MISSING={total['missing']:,}")
    print("WAGE_FIX_V2_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

