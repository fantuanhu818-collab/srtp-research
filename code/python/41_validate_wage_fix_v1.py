"""独立复核 wage_fix_v1：不复用 38 号程序的向量化逻辑，全部用 SQL 重算。

复核内容：
1. 行数、字段、ID唯一性、非空；
2. 逐条重算应修正记录，与输出表比对（值、标志、规则、倍数、对数）；
3. 原值与 cleaned_v1 逐条一致；
4. 与 confirmed_core_v2 的ID覆盖关系；
5. 行为断言：2018平台11≥3万全部修正、2019平台11零修正、
   2021平台72的3万—6万不修正、平台64修正后上限合理；
6. 年度前后分布与汇总表一致。

输出：outputs/qc/wage_fix_v1_validation.md
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v1.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "wage_fix_v1_summary.csv"
DIST_PATH = QC_ROOT / "wage_fix_v1_distribution.csv"
REPORT_PATH = QC_ROOT / "wage_fix_v1_validation.md"

EXPECTED_INPUT_ROWS = 5_235_461
EXPECTED_V2_ROWS = 5_235_398
EXPECTED_FIXED_ROWS = 135_930
EXTREME_THRESHOLD = 100_000.0
EXPECTED_COLUMNS = [
    "source_record_id", "wage_mid_orig", "ln_wage_orig", "wage_mid_fixed",
    "ln_wage_fixed", "wage_fix_flag", "wage_fix_rule", "wage_fix_factor", "wage_fix_version",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    rules_config = load_json(RULES_PATH)
    cleaned_glob = str(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet").replace("\\", "/")
    feature_glob = str(Path(storage["features_root"]) / "wage_fix_v1" / "jobs_*_wage_fix.parquet").replace("\\", "/")
    v2_glob = str(Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_*_confirmed_core.parquet").replace("\\", "/")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    checks: list[tuple[str, str, str]] = []

    def record(name: str, expected: str, actual: str, ok: bool) -> None:
        checks.append((name, expected, actual, "通过" if ok else "失败"))
        if not ok:
            raise RuntimeError(f"复核失败：{name}（预期{expected}，实际{actual}）")

    # 1. 结构
    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{feature_glob}')").fetchall()]
    record("字段清单", ",".join(EXPECTED_COLUMNS), ",".join(columns), columns == EXPECTED_COLUMNS)

    rows = con.execute(f"SELECT count(*) FROM read_parquet('{feature_glob}')").fetchone()[0]
    record("总行数", f"{EXPECTED_INPUT_ROWS:,}", f"{rows:,}", rows == EXPECTED_INPUT_ROWS)

    unique_ids = con.execute(f"SELECT count(DISTINCT source_record_id) FROM read_parquet('{feature_glob}')").fetchone()[0]
    record("source_record_id唯一数", f"{EXPECTED_INPUT_ROWS:,}", f"{unique_ids:,}", unique_ids == EXPECTED_INPUT_ROWS)

    nulls = con.execute(
        f"""SELECT count(*) FROM read_parquet('{feature_glob}')
            WHERE source_record_id IS NULL OR wage_mid_orig IS NULL OR wage_mid_fixed IS NULL
               OR ln_wage_orig IS NULL OR ln_wage_fixed IS NULL OR wage_fix_flag IS NULL
               OR wage_fix_factor IS NULL OR wage_fix_version IS NULL"""
    ).fetchone()[0]
    record("关键字段缺失", "0", f"{nulls:,}", nulls == 0)

    bad_flag = con.execute(
        f"SELECT count(*) FROM read_parquet('{feature_glob}') WHERE wage_fix_flag NOT IN (0,1)"
    ).fetchone()[0]
    record("wage_fix_flag取值越界", "0", f"{bad_flag:,}", bad_flag == 0)

    bad_version = con.execute(
        f"SELECT count(*) FROM read_parquet('{feature_glob}') WHERE wage_fix_version <> 'wage_fix_v1'"
    ).fetchone()[0]
    record("版本号异常", "0", f"{bad_version:,}", bad_version == 0)

    # 2. 用SQL独立重算应修正记录
    values_sql = ",\n            ".join(
        f"('{rule['rule_id']}', {int(rule['year'])}, '{rule['platform']}', {float(rule['min_wage'])}, {float(rule['factor'])})"
        for rule in rules_config["rules"]
    )
    recompute = f"""
        WITH rules(rule_id, yr, platform, min_wage, factor) AS (VALUES {values_sql}),
        src AS (
            SELECT 来源记录ID AS id, 招聘发布年份 AS y, 来源 AS p, 月薪代表值 AS w
            FROM read_parquet('{cleaned_glob}')
        ),
        exp AS (
            SELECT src.id, src.w,
                   coalesce(rules.factor, 1.0) AS factor,
                   coalesce(rules.rule_id, '') AS rule_id
            FROM src LEFT JOIN rules
              ON rules.yr = src.y AND rules.platform = src.p AND src.w >= rules.min_wage
        ),
        out AS (
            SELECT source_record_id AS id, wage_mid_orig, wage_mid_fixed, wage_fix_flag,
                   wage_fix_rule, wage_fix_factor, ln_wage_orig, ln_wage_fixed
            FROM read_parquet('{feature_glob}')
        )
        SELECT count(*) AS joined,
               sum(CASE WHEN abs(exp.w - out.wage_mid_orig) > 1e-9 THEN 1 ELSE 0 END) AS orig_mismatch,
               sum(CASE WHEN abs(exp.w / exp.factor - out.wage_mid_fixed) > 1e-9 THEN 1 ELSE 0 END) AS fixed_mismatch,
               sum(CASE WHEN abs(exp.factor - out.wage_fix_factor) > 1e-9 THEN 1 ELSE 0 END) AS factor_mismatch,
               sum(CASE WHEN exp.rule_id <> out.wage_fix_rule THEN 1 ELSE 0 END) AS rule_mismatch,
               sum(CASE WHEN (exp.factor <> 1.0) <> (out.wage_fix_flag = 1) THEN 1 ELSE 0 END) AS flag_mismatch,
               sum(CASE WHEN abs(ln(exp.w) - out.ln_wage_orig) > 1e-9 THEN 1 ELSE 0 END) AS ln_orig_mismatch,
               sum(CASE WHEN abs(ln(exp.w / exp.factor) - out.ln_wage_fixed) > 1e-9 THEN 1 ELSE 0 END) AS ln_fixed_mismatch,
               sum(CASE WHEN exp.factor <> 1.0 THEN 1 ELSE 0 END) AS expected_fixed
        FROM exp JOIN out USING (id)
    """
    r = con.execute(recompute).fetchone()
    record("可匹配记录数", f"{EXPECTED_INPUT_ROWS:,}", f"{int(r[0]):,}", int(r[0]) == EXPECTED_INPUT_ROWS)
    record("原值与cleaned_v1不一致", "0", f"{int(r[1]):,}", int(r[1]) == 0)
    record("修正值与SQL重算不一致", "0", f"{int(r[2]):,}", int(r[2]) == 0)
    record("倍数不一致", "0", f"{int(r[3]):,}", int(r[3]) == 0)
    record("规则标签不一致", "0", f"{int(r[4]):,}", int(r[4]) == 0)
    record("修正标志不一致", "0", f"{int(r[5]):,}", int(r[5]) == 0)
    record("原值对数不一致", "0", f"{int(r[6]):,}", int(r[6]) == 0)
    record("修正值对数不一致", "0", f"{int(r[7]):,}", int(r[7]) == 0)
    record("应修正条数", f"{EXPECTED_FIXED_ROWS:,}", f"{int(r[8]):,}", int(r[8]) == EXPECTED_FIXED_ROWS)

    actual_fixed = con.execute(f"SELECT sum(wage_fix_flag) FROM read_parquet('{feature_glob}')").fetchone()[0]
    record("实际修正条数", f"{EXPECTED_FIXED_ROWS:,}", f"{int(actual_fixed):,}", int(actual_fixed) == EXPECTED_FIXED_ROWS)

    # 3. 与回归底表的覆盖关系
    v2_ids = con.execute(f"SELECT count(*) FROM read_parquet('{v2_glob}')").fetchone()[0]
    record("confirmed_core_v2行数", f"{EXPECTED_V2_ROWS:,}", f"{v2_ids:,}", v2_ids == EXPECTED_V2_ROWS)
    unmatched = con.execute(
        f"""SELECT count(*) FROM read_parquet('{v2_glob}') v
            LEFT JOIN read_parquet('{feature_glob}') f USING (source_record_id)
            WHERE f.source_record_id IS NULL"""
    ).fetchone()[0]
    record("v2记录在修正表中缺失", "0", f"{unmatched:,}", unmatched == 0)

    # 4. 行为断言（用平台字段，需要回连cleaned_v1）
    behaviour_sql = f"""
        WITH src AS (
            SELECT 来源记录ID AS id, 招聘发布年份 AS y, 来源 AS p, 月薪代表值 AS w
            FROM read_parquet('{cleaned_glob}')
        ),
        out AS (SELECT source_record_id AS id, wage_fix_flag, wage_mid_fixed FROM read_parquet('{feature_glob}'))
        SELECT
          sum(CASE WHEN y=2018 AND p='平台11' AND w>=30000 AND wage_fix_flag=0 THEN 1 ELSE 0 END) AS p11_18_high_unfixed,
          sum(CASE WHEN y=2018 AND p='平台11' AND w<30000 AND wage_fix_flag=1 THEN 1 ELSE 0 END) AS p11_18_low_fixed,
          sum(CASE WHEN y=2019 AND p='平台11' AND wage_fix_flag=1 THEN 1 ELSE 0 END) AS p11_19_fixed,
          sum(CASE WHEN y=2021 AND p='平台72' AND w>=30000 AND w<60000 AND wage_fix_flag=1 THEN 1 ELSE 0 END) AS p72_21_mid_fixed,
          sum(CASE WHEN y=2021 AND p='平台72' AND w>=60000 AND wage_fix_flag=0 THEN 1 ELSE 0 END) AS p72_21_high_unfixed,
          max(CASE WHEN y=2019 AND p='平台64' THEN wage_mid_fixed END) AS p64_19_max,
          max(CASE WHEN y=2018 AND p='平台64' THEN wage_mid_fixed END) AS p64_18_max,
          sum(CASE WHEN p='平台64' AND y IN (2018,2019) AND w < 10000 AND wage_fix_flag=1 THEN 1 ELSE 0 END) AS p64_low_fixed,
          sum(CASE WHEN p='平台64' AND y IN (2018,2019) AND w = 6500 AND wage_mid_fixed = 6500 THEN 1 ELSE 0 END) AS p64_6500_kept,
          sum(CASE WHEN p='平台64' AND y IN (2018,2019) AND w = 6500 THEN 1 ELSE 0 END) AS p64_6500_total
        FROM src JOIN out USING (id)
    """
    b = con.execute(behaviour_sql).fetchone()
    record("2018平台11≥3万未修正条数", "0", f"{int(b[0]):,}", int(b[0]) == 0)
    record("2018平台11<3万被误修条数", "0", f"{int(b[1]):,}", int(b[1]) == 0)
    record("2019平台11被误修条数", "0", f"{int(b[2]):,}", int(b[2]) == 0)
    record("2021平台72的3万—6万被误修条数", "0", f"{int(b[3]):,}", int(b[3]) == 0)
    record("2021平台72≥6万未修正条数", "0", f"{int(b[4]):,}", int(b[4]) == 0)
    record("平台64修正后上限≤75000（2019）", "≤75000", f"{float(b[5]):,.0f}", float(b[5]) <= 75_000)
    record("平台64修正后上限≤55000（2018）", "≤55000", f"{float(b[6]):,.0f}", float(b[6]) <= 55_000)
    record("平台64低于1万被误修条数", "0", f"{int(b[7]):,}", int(b[7]) == 0)
    record(
        "平台64原值6500元的记录保持原值",
        f"{int(b[9]):,}",
        f"{int(b[8]):,}",
        int(b[8]) == int(b[9]) and int(b[9]) > 0,
    )

    # 5. 分布与汇总表一致
    dist_rows = {row["year"]: row for row in read_csv_rows(DIST_PATH)}
    year_expr = "regexp_extract(filename, 'jobs_([0-9]{4})_', 1)"
    live = con.execute(
        f"""
        SELECT {year_expr} AS yr,
               count(*) AS rows, sum(wage_fix_flag) AS fixed,
               round(avg(wage_mid_orig),2), round(avg(wage_mid_fixed),2),
               round(median(wage_mid_orig),2), round(median(wage_mid_fixed),2),
               round(avg(CASE WHEN wage_mid_orig > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END),6),
               round(avg(CASE WHEN wage_mid_fixed > {EXTREME_THRESHOLD} THEN 1 ELSE 0 END),6),
               round(quantile_cont(wage_mid_fixed,0.99),2), round(max(wage_mid_fixed),2)
        FROM read_parquet('{feature_glob}', filename=true) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    dist_mismatch = 0
    for r in live:
        row = dist_rows.get(str(int(r[0])))
        if row is None:
            dist_mismatch += 1
            continue
        pairs = [
            (int(r[1]), int(row["rows"])), (int(r[2]), int(row["fixed_rows"])),
            (float(r[3]), float(row["mean_wage_before"])), (float(r[4]), float(row["mean_wage_after"])),
            (float(r[5]), float(row["median_wage_before"])), (float(r[6]), float(row["median_wage_after"])),
            (float(r[7]), float(row["share_over_100k_before"])), (float(r[8]), float(row["share_over_100k_after"])),
            (float(r[9]), float(row["p99_wage_after"])), (float(r[10]), float(row["max_wage_after"])),
        ]
        dist_mismatch += sum(1 for a, b2 in pairs if abs(a - b2) > 1e-4)
    record("年度分布与CSV不一致项", "0", str(dist_mismatch), dist_mismatch == 0)

    total_row = dist_rows.get("合计")
    record("汇总表含合计行", "存在", "存在" if total_row else "缺失", total_row is not None)

    summary_rows = {row["year"]: row for row in read_csv_rows(SUMMARY_PATH)}
    record("汇总表年度数", "9", str(len(summary_rows)), len(summary_rows) == 9)

    # 6. 修正后仍超过10万的残留
    remain = con.execute(
        f"""SELECT count(*), max(wage_mid_fixed) FROM read_parquet('{feature_glob}') WHERE wage_mid_fixed > {EXTREME_THRESHOLD}"""
    ).fetchone()
    remain_n, remain_max = int(remain[0]), float(remain[1])

    # 报告
    lines: list[str] = []
    lines.append("# wage_fix_v1 独立复核报告\n")
    lines.append(f"结论：通过。{len(checks)}项检查全部通过，工资修正特征表可以用于合并与回归。\n")
    lines.append("## 一、检查项\n")
    lines.append("|检查项|预期|实际|结果|")
    lines.append("|---|---|---|---|")
    for name, expected, actual, status in checks:
        lines.append(f"|{name}|{expected}|{actual}|{status}|")
    lines.append("")
    lines.append("## 二、修正规则与命中条数\n")
    lines.append("|规则|年份|平台|阈值|倍数|命中条数|")
    lines.append("|---|---:|---|---:|---:|---:|")
    for rule in rules_config["rules"]:
        n = con.execute(
            f"SELECT count(*) FROM read_parquet('{feature_glob}') WHERE wage_fix_rule = '{rule['rule_id']}'"
        ).fetchone()[0]
        lines.append(
            f"|{rule['label']}|{rule['year']}|{rule['platform']}|{rule['min_wage']:,.0f}|÷{rule['factor']:g}|{int(n):,}|"
        )
    lines.append("")
    lines.append("## 三、工资分布前后对比\n")
    lines.append("|年份|修正条数|平均月薪 原→修正|中位月薪 原→修正|>10万占比 原→修正|")
    lines.append("|---|---:|---|---|---|")
    for year in [str(y) for y in range(2018, 2026)]:
        row = dist_rows[year]
        lines.append(
            f"|{year}|{int(row['fixed_rows']):,}|{float(row['mean_wage_before']):,.0f} → {float(row['mean_wage_after']):,.0f}"
            f"|{float(row['median_wage_before']):,.0f} → {float(row['median_wage_after']):,.0f}"
            f"|{float(row['share_over_100k_before'])*100:.2f}% → {float(row['share_over_100k_after'])*100:.2f}%|"
        )
    t = dist_rows["合计"]
    lines.append(
        f"|合计|{int(t['fixed_rows']):,}|{float(t['mean_wage_before']):,.0f} → {float(t['mean_wage_after']):,.0f}"
        f"|{float(t['median_wage_before']):,.0f} → {float(t['median_wage_after']):,.0f}"
        f"|{float(t['share_over_100k_before'])*100:.2f}% → {float(t['share_over_100k_after'])*100:.2f}%|"
    )
    lines.append("")
    lines.append("## 四、已知残留\n")
    lines.append(
        f"- 修正后仍有 {remain_n:,} 条月薪超过10万，最大值 {remain_max:,.0f}。这些不属于已证实的成批单位错误，"
        "留待分析阶段统一缩尾或截断，本表不处理；清单见`outputs/qc/wage_fix_v1_remaining_extremes.csv`。"
    )
    lines.append("- 2018年平台38（46条>10万，样本过小）未处理；平台64以外的同类问题需先有配对或跨年分布证据。")
    lines.append("- 本表只改工资，不改学历、经验、企业、城市和其他任何字段。")
    lines.append("")
    lines.append("## 五、复现\n")
    lines.append("```powershell")
    lines.append("powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/40_build_wage_fix_v1.py")
    lines.append("powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/41_validate_wage_fix_v1.py")
    lines.append("```")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"WAGE_FIX_V1_VALIDATION={REPORT_PATH}")
    print("WAGE_FIX_V1_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
