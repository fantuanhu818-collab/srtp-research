"""构造工资修正特征表 wage_fix_v1。

背景：cleaned_v1 的工资规则只处理非数值、≤0、上下限颠倒和单端缺失，不检查单位。
2018年平台11、2021年平台72有一批广告把年薪写进了月薪字段；2018—2019年平台64
整平台被放大约10倍。本脚本只按 config/wage_fix_rules_v1.json 中已证实的
“年份×平台”规则修正这些记录，其余记录一律保持原值。

不修改 cleaned_v1，不修改 confirmed_core_v2，不删记录，不做缩尾。
输出：<features_root>/wage_fix_v1/jobs_{year}_wage_fix.parquet
      <features_root>/wage_fix_v1/manifest.json
      outputs/qc/wage_fix_v1_summary.csv
      outputs/qc/wage_fix_v1_distribution.csv
      outputs/qc/wage_fix_v1_remaining_extremes.csv
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
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v1.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "wage_fix_v1_summary.csv"
DIST_PATH = QC_ROOT / "wage_fix_v1_distribution.csv"
EXTREMES_PATH = QC_ROOT / "wage_fix_v1_remaining_extremes.csv"

YEARS = tuple(range(2018, 2026))
FEATURE_VERSION = "wage_fix_v1"
EXPECTED_INPUT_ROWS = 5_235_461
EXPECTED_V2_ROWS = 5_235_398
EXTREME_THRESHOLD = 100_000.0

# 已核实的各规则命中条数，运行中必须完全一致，否则说明输入数据或规则被改动过。
EXPECTED_RULE_ROWS = {
    "annual_div12_p11_2018": 118_329,
    "annual_div12_p72_2021": 7_199,
    "scale_div10_p64_2018": 547,
    "scale_div10_p64_2019": 9_855,
}

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("wage_mid_orig", pa.float64(), nullable=False),
        pa.field("ln_wage_orig", pa.float64(), nullable=False),
        pa.field("wage_mid_fixed", pa.float64(), nullable=False),
        pa.field("ln_wage_fixed", pa.float64(), nullable=False),
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


def snapshot(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    rules_config = load_json(RULES_PATH)
    input_root = Path(storage["curated_root"]) / "cleaned_v1"
    output_root = Path(storage["features_root"]) / FEATURE_VERSION
    output_root.mkdir(parents=True, exist_ok=True)

    rules = rules_config["rules"]
    rule_by_key = {(int(rule["year"]), rule["platform"]): rule for rule in rules}
    if len(rule_by_key) != len(rules):
        raise RuntimeError("规则中存在重复的年份×平台")

    summary_rows: list[dict] = []
    distribution_rows: list[dict] = []
    rule_rows: dict[str, int] = {rule["rule_id"]: 0 for rule in rules}
    input_snapshots: dict[str, tuple[int, int]] = {}
    total_input = 0
    total_fixed = 0

    for year in YEARS:
        source_path = input_root / f"jobs_{year}_cleaned.parquet"
        output_path = output_root / f"jobs_{year}_wage_fix.parquet"
        temp_path = output_path.with_suffix(".parquet.tmp")
        input_snapshots[str(source_path)] = snapshot(source_path)

        frame = pd.read_parquet(source_path, columns=["来源记录ID", "来源", "月薪代表值", "招聘发布年份"])
        input_rows = len(frame)
        if frame["来源记录ID"].duplicated().any():
            raise RuntimeError(f"{year}年来源记录ID重复")
        if (frame["招聘发布年份"] != year).any():
            raise RuntimeError(f"{year}年文件中存在其他年份记录")
        wage = pd.to_numeric(frame["月薪代表值"], errors="coerce")
        if wage.isna().any() or (wage <= 0).any():
            raise RuntimeError(f"{year}年存在无效月薪代表值")

        wage_values = wage.to_numpy(dtype="float64")
        platform = frame["来源"].fillna("").astype(str)
        factor = np.ones(input_rows, dtype="float64")
        rule_name = np.full(input_rows, "", dtype=object)

        for (rule_year, rule_platform), rule in rule_by_key.items():
            if rule_year != year:
                continue
            mask = (platform == rule_platform).to_numpy() & (wage_values >= float(rule["min_wage"]))
            if rule.get("max_wage") is not None:
                mask &= wage_values < float(rule["max_wage"])
            if not mask.any():
                continue
            factor[mask] = float(rule["factor"])
            rule_name[mask] = rule["rule_id"]

        fixed = wage_values / factor
        flag = (factor != 1.0).astype("int8")

        table = pa.Table.from_arrays(
            [
                pa.array(frame["来源记录ID"].to_numpy(), type=pa.string()),
                pa.array(wage_values, type=pa.float64()),
                pa.array(np.log(wage_values), type=pa.float64()),
                pa.array(fixed, type=pa.float64()),
                pa.array(np.log(fixed), type=pa.float64()),
                pa.array(flag, type=pa.int8()),
                pa.array(rule_name, type=pa.string()),
                pa.array(factor, type=pa.float64()),
                pa.array(np.full(input_rows, FEATURE_VERSION, dtype=object), type=pa.string()),
            ],
            schema=OUTPUT_SCHEMA,
        )
        if table.schema.names != OUTPUT_SCHEMA.names:
            raise RuntimeError("输出字段顺序异常")
        pq.write_table(table, temp_path, compression="zstd")

        check = pq.ParquetFile(temp_path)
        if check.metadata.num_rows != input_rows:
            raise RuntimeError(f"{year}年输出行数异常")
        check.close()
        os.replace(temp_path, output_path)

        for name in rule_rows:
            rule_rows[name] += int((rule_name == name).sum())

        fixed_count = int(flag.sum())
        total_input += input_rows
        total_fixed += fixed_count
        summary_rows.append(
            {
                "year": year,
                "input_rows": input_rows,
                "fixed_rows": fixed_count,
                "fixed_share": round(fixed_count / input_rows, 6),
                "mean_wage_before": round(float(wage_values.mean()), 2),
                "mean_wage_after": round(float(fixed.mean()), 2),
                "median_wage_before": round(float(np.median(wage_values)), 2),
                "median_wage_after": round(float(np.median(fixed)), 2),
                "share_over_100k_before": round(float((wage_values > EXTREME_THRESHOLD).mean()), 6),
                "share_over_100k_after": round(float((fixed > EXTREME_THRESHOLD).mean()), 6),
                "output_path": str(output_path),
            }
        )
        print(f"{year}: rows={input_rows:,} fixed={fixed_count:,} -> {output_path.name}", flush=True)

    if total_input != EXPECTED_INPUT_ROWS:
        raise RuntimeError(f"输入总量异常：{total_input:,}")
    for name, expected in EXPECTED_RULE_ROWS.items():
        if rule_rows[name] != expected:
            raise RuntimeError(f"规则{name}命中{rule_rows[name]:,}条，预期{expected:,}条")
    if total_fixed != sum(EXPECTED_RULE_ROWS.values()):
        raise RuntimeError(f"修正总量异常：{total_fixed:,}")
    for path, old_snapshot in input_snapshots.items():
        if snapshot(Path(path)) != old_snapshot:
            raise RuntimeError(f"输入文件在运行期间发生变化：{path}")

    # 用写出的Parquet回读，保证QC表反映磁盘上的真实结果，而不是内存里的中间数组
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    out_glob = str(output_root / "jobs_*_wage_fix.parquet").replace("\\", "/")
    year_expr = "regexp_extract(filename, 'jobs_([0-9]{4})_', 1)"

    rows = con.execute(
        f"""
        SELECT {year_expr} AS yr,
               count(*) AS rows,
               sum(wage_fix_flag) AS fixed,
               avg(wage_mid_orig) AS mean_before,
               avg(wage_mid_fixed) AS mean_after,
               median(wage_mid_orig) AS median_before,
               median(wage_mid_fixed) AS median_after,
               avg(CASE WHEN wage_mid_orig > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END) AS share_before,
               avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END) AS share_after,
               quantile_cont(wage_mid_fixed, 0.99) AS p99_after,
               max(wage_mid_fixed) AS max_after
        FROM read_parquet('{out_glob}', filename=true)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    for r in rows:
        distribution_rows.append(
            {
                "year": int(r[0]),
                "rows": int(r[1]),
                "fixed_rows": int(r[2]),
                "mean_wage_before": round(float(r[3]), 2),
                "mean_wage_after": round(float(r[4]), 2),
                "median_wage_before": round(float(r[5]), 2),
                "median_wage_after": round(float(r[6]), 2),
                "share_over_100k_before": round(float(r[7]), 6),
                "share_over_100k_after": round(float(r[8]), 6),
                "p99_wage_after": round(float(r[9]), 2),
                "max_wage_after": round(float(r[10]), 2),
            }
        )

    total_stats = con.execute(
        f"""
        SELECT count(*), sum(wage_fix_flag), avg(wage_mid_orig), avg(wage_mid_fixed),
               median(wage_mid_orig), median(wage_mid_fixed),
               avg(CASE WHEN wage_mid_orig > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END),
               avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END),
               quantile_cont(wage_mid_fixed, 0.99), max(wage_mid_fixed)
        FROM read_parquet('{out_glob}')
        """
    ).fetchone()
    total = {
        "year": "合计",
        "rows": int(total_stats[0]),
        "fixed_rows": int(total_stats[1]),
        "mean_wage_before": round(float(total_stats[2]), 2),
        "mean_wage_after": round(float(total_stats[3]), 2),
        "median_wage_before": round(float(total_stats[4]), 2),
        "median_wage_after": round(float(total_stats[5]), 2),
        "share_over_100k_before": round(float(total_stats[6]), 6),
        "share_over_100k_after": round(float(total_stats[7]), 6),
        "p99_wage_after": round(float(total_stats[8]), 2),
        "max_wage_after": round(float(total_stats[9]), 2),
    }
    distribution_rows.append(total)

    summary_rows.append(
        {
            "year": "合计",
            "input_rows": total["rows"],
            "fixed_rows": total["fixed_rows"],
            "fixed_share": round(total["fixed_rows"] / total["rows"], 6),
            "mean_wage_before": total["mean_wage_before"],
            "mean_wage_after": total["mean_wage_after"],
            "median_wage_before": total["median_wage_before"],
            "median_wage_after": total["median_wage_after"],
            "share_over_100k_before": total["share_over_100k_before"],
            "share_over_100k_after": total["share_over_100k_after"],
            "output_path": str(output_root),
        }
    )
    write_csv(SUMMARY_PATH, summary_rows)
    write_csv(DIST_PATH, distribution_rows)

    # 修正后仍超过10万的记录，按“年份×处理规则”汇总，供后续缩尾讨论
    extremes = con.execute(
        f"""
        SELECT {year_expr} AS yr,
               CASE WHEN wage_fix_rule = '' THEN '未修正' ELSE wage_fix_rule END AS grp,
               count(*) AS n,
               round(median(wage_mid_fixed), 1) AS med,
               round(max(wage_mid_fixed), 1) AS mx
        FROM read_parquet('{out_glob}', filename=true)
        WHERE wage_mid_fixed > {EXTREME_THRESHOLD}
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 40
        """
    ).fetchall()
    extremes_rows = [
        {"year": int(r[0]), "group": r[1], "rows": int(r[2]),
         "median_fixed_wage": float(r[3]), "max_fixed_wage": float(r[4])}
        for r in extremes
    ] or [{"year": "", "group": "无", "rows": 0, "median_fixed_wage": 0.0, "max_fixed_wage": 0.0}]
    write_csv(EXTREMES_PATH, extremes_rows)

    manifest = {
        "version": FEATURE_VERSION,
        "input_version": "cleaned_v1",
        "input_rows": total_input,
        "output_rows": total_input,
        "fixed_rows": total_fixed,
        "v2_joinable_rows": EXPECTED_V2_ROWS,
        "join_key": "source_record_id",
        "rules_file": str(RULES_PATH),
        "rules": rules,
        "rule_counts": rule_rows,
        "untouched_rows": total_input - total_fixed,
        "created_variables": OUTPUT_SCHEMA.names[1:],
        "usage": "工资变量用 wage_mid_fixed / ln_wage_fixed；原值保留在 wage_mid_orig / ln_wage_orig；wage_fix_flag=1 表示该条被修正过",
        "summary_file": str(SUMMARY_PATH),
        "distribution_file": str(DIST_PATH),
        "remaining_extremes_file": str(EXTREMES_PATH),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"WAGE_FIX_V1_OUTPUT={output_root}")
    print(f"WAGE_FIX_V1_FIXED={total_fixed:,}")
    print("WAGE_FIX_V1_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
