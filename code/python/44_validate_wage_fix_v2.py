"""独立复核 wage_fix_v2：不复用构建逻辑，全部用 SQL 从 cleaned_v1 与 wage_fix_v1 重算。

复核重点：
1. 结构、行数、ID唯一、flag取值、占位值确实全部置缺失；
2. 未置缺失的记录，修正后工资与 wage_fix_v1 逐条一致；
3. ln_wage_fixed 与 ln(wage_mid_fixed) 逐条一致，且缺失记录的对数也为缺失；
4. 缺失集合与“两端=888888”的记录集合完全相等（不多不少）；
5. 分布表与汇总表一致。

输出：outputs/qc/wage_fix_v2_validation.md
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULES_PATH = PROJECT_ROOT / "config" / "wage_fix_rules_v2.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
DIST_PATH = QC_ROOT / "wage_fix_v2_distribution.csv"
SUMMARY_PATH = QC_ROOT / "wage_fix_v2_summary.csv"
REPORT_PATH = QC_ROOT / "wage_fix_v2_validation.md"

EXPECTED_ROWS = 5_235_461
EXPECTED_MISSING = 46
EXPECTED_DIVIDED = 135_930
PLACEHOLDER = 888_888.0
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
    rules = load_json(RULES_PATH)
    rule_id = rules["placeholder_rules"][0]["rule_id"]
    cleaned = str(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet").replace("\\", "/")
    base = str(Path(storage["features_root"]) / "wage_fix_v1" / "jobs_*_wage_fix.parquet").replace("\\", "/")
    cur = str(Path(storage["features_root"]) / "wage_fix_v2" / "jobs_*_wage_fix.parquet").replace("\\", "/")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    checks: list[tuple[str, str, str, str]] = []

    def record(name: str, expected: str, actual: str, ok: bool) -> None:
        checks.append((name, expected, actual, "通过" if ok else "失败"))
        if not ok:
            raise RuntimeError(f"复核失败：{name}（预期{expected}，实际{actual}）")

    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{cur}')").fetchall()]
    record("字段清单", ",".join(EXPECTED_COLUMNS), ",".join(columns), columns == EXPECTED_COLUMNS)

    rows = con.execute(f"SELECT count(*) FROM read_parquet('{cur}')").fetchone()[0]
    record("总行数", f"{EXPECTED_ROWS:,}", f"{rows:,}", rows == EXPECTED_ROWS)

    uniq = con.execute(f"SELECT count(DISTINCT source_record_id) FROM read_parquet('{cur}')").fetchone()[0]
    record("source_record_id唯一数", f"{EXPECTED_ROWS:,}", f"{uniq:,}", uniq == EXPECTED_ROWS)

    bad_flag = con.execute(f"SELECT count(*) FROM read_parquet('{cur}') WHERE wage_fix_flag NOT IN (0,1,2)").fetchone()[0]
    record("wage_fix_flag取值越界", "0", f"{bad_flag:,}", bad_flag == 0)

    # 占位值集合必须与缺失集合完全相等
    sets = con.execute(
        f"""
        WITH src AS (
            SELECT 来源记录ID AS id, 最低月薪 AS lo, 最高月薪 AS hi FROM read_parquet('{cleaned}')
        ),
        out AS (
            SELECT source_record_id AS id, wage_mid_fixed, ln_wage_fixed, wage_fix_flag, wage_fix_rule
            FROM read_parquet('{cur}')
        ),
        j AS (SELECT src.id, src.lo, src.hi, out.wage_mid_fixed, out.ln_wage_fixed, out.wage_fix_flag, out.wage_fix_rule
              FROM src JOIN out USING (id))
        SELECT
          count(*) FILTER (WHERE lo = {PLACEHOLDER} AND hi = {PLACEHOLDER}) AS placeholder,
          count(*) FILTER (WHERE wage_mid_fixed IS NULL) AS is_null,
          count(*) FILTER (WHERE lo = {PLACEHOLDER} AND hi = {PLACEHOLDER} AND wage_mid_fixed IS NOT NULL) AS placeholder_not_null,
          count(*) FILTER (WHERE wage_mid_fixed IS NULL AND NOT (lo = {PLACEHOLDER} AND hi = {PLACEHOLDER})) AS null_not_placeholder,
          count(*) FILTER (WHERE wage_mid_fixed IS NOT NULL AND (lo = {PLACEHOLDER} OR hi = {PLACEHOLDER})) AS any_placeholder_left,
          count(*) FILTER (WHERE wage_mid_fixed IS NULL AND ln_wage_fixed IS NOT NULL) AS null_wage_has_ln,
          count(*) FILTER (WHERE wage_mid_fixed IS NOT NULL AND ln_wage_fixed IS NULL) AS wage_without_ln,
          count(*) FILTER (WHERE wage_fix_flag = 2 AND wage_fix_rule <> '{rule_id}') AS wrong_rule,
          count(*) FILTER (WHERE wage_fix_flag = 2 AND wage_mid_fixed IS NOT NULL) AS flag2_not_null,
          sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END) AS divided
        FROM j
        """
    ).fetchone()
    record("两端=888888的记录数", f"{EXPECTED_MISSING}", f"{int(sets[0])}", int(sets[0]) == EXPECTED_MISSING)
    record("置缺失记录数", f"{EXPECTED_MISSING}", f"{int(sets[1])}", int(sets[1]) == EXPECTED_MISSING)
    record("占位值记录仍保留工资", "0", f"{int(sets[2])}", int(sets[2]) == 0)
    record("缺失但非占位值的记录", "0", f"{int(sets[3])}", int(sets[3]) == 0)
    record("任一端仍为888888的有效记录", "0", f"{int(sets[4])}", int(sets[4]) == 0)
    record("工资缺失但对数非缺失", "0", f"{int(sets[5])}", int(sets[5]) == 0)
    record("工资非缺失但对数缺失", "0", f"{int(sets[6])}", int(sets[6]) == 0)
    record("flag=2但规则标签错误", "0", f"{int(sets[7])}", int(sets[7]) == 0)
    record("flag=2但工资非缺失", "0", f"{int(sets[8])}", int(sets[8]) == 0)
    record("修正（÷12/÷10）条数", f"{EXPECTED_DIVIDED:,}", f"{int(sets[9]):,}", int(sets[9]) == EXPECTED_DIVIDED)

    # 非缺失记录必须与 v1 完全一致（v2 只做了置缺失，不该改动其他值）
    cmp = con.execute(
        f"""
        WITH b AS (SELECT source_record_id AS id, wage_mid_fixed AS w1, ln_wage_fixed AS ln1,
                          wage_fix_flag AS f1, wage_fix_rule AS r1 FROM read_parquet('{base}')),
             c AS (SELECT source_record_id AS id, wage_mid_fixed AS w2, ln_wage_fixed AS ln2,
                          wage_fix_flag AS f2, wage_fix_rule AS r2 FROM read_parquet('{cur}'))
        SELECT count(*),
          sum(CASE WHEN w2 IS NOT NULL AND abs(w2 - w1) > 1e-9 THEN 1 ELSE 0 END) wage_diff,
          sum(CASE WHEN w2 IS NOT NULL AND abs(ln2 - ln1) > 1e-9 THEN 1 ELSE 0 END) ln_diff,
          sum(CASE WHEN w2 IS NOT NULL AND f2 <> f1 THEN 1 ELSE 0 END) flag_diff,
          sum(CASE WHEN w2 IS NOT NULL AND r2 <> r1 THEN 1 ELSE 0 END) rule_diff,
          sum(CASE WHEN w2 IS NOT NULL AND abs(ln2 - ln(w2)) > 1e-9 THEN 1 ELSE 0 END) ln_bad
        FROM b JOIN c USING (id)
        """
    ).fetchone()
    record("与v1可匹配记录数", f"{EXPECTED_ROWS:,}", f"{int(cmp[0]):,}", int(cmp[0]) == EXPECTED_ROWS)
    record("工资与v1不一致（非缺失）", "0", f"{int(cmp[1]):,}", int(cmp[1]) == 0)
    record("对数与v1不一致（非缺失）", "0", f"{int(cmp[2]):,}", int(cmp[2]) == 0)
    record("修正标志与v1不一致（非缺失）", "0", f"{int(cmp[3]):,}", int(cmp[3]) == 0)
    record("规则标签与v1不一致（非缺失）", "0", f"{int(cmp[4]):,}", int(cmp[4]) == 0)
    record("对数不等于ln(工资)的条数", "0", f"{int(cmp[5]):,}", int(cmp[5]) == 0)

    # 分布表一致性
    dist_rows = {row["year"]: row for row in read_csv_rows(DIST_PATH)}
    live = con.execute(
        f"""
        SELECT regexp_extract(filename, 'jobs_([0-9]{{4}})_', 1) AS yr, count(*),
               sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag = 2 THEN 1 ELSE 0 END),
               count(wage_mid_fixed), round(avg(wage_mid_fixed), 2), round(median(wage_mid_fixed), 2),
               round(quantile_cont(wage_mid_fixed, 0.99), 2), round(max(wage_mid_fixed), 2),
               round(avg(CASE WHEN wage_mid_fixed > 100000 THEN 1 ELSE 0 END), 6)
        FROM read_parquet('{cur}', filename=true) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    mismatches = 0
    for r in live:
        row = dist_rows.get(str(int(r[0])))
        if row is None:
            mismatches += 1
            continue
        pairs = [
            (int(r[1]), int(row["rows"])), (int(r[2]), int(row["divided"])),
            (int(r[3]), int(row["set_missing"])), (int(r[4]), int(row["valid_rows"])),
            (float(r[5]), float(row["mean_wage"])), (float(r[6]), float(row["median_wage"])),
            (float(r[7]), float(row["p99_wage"])), (float(r[8]), float(row["max_wage"])),
            (float(r[9]), float(row["share_over_100k"])),
        ]
        mismatches += sum(1 for a, b in pairs if abs(a - b) > 1e-3)
    record("年度分布与CSV不一致项", "0", str(mismatches), mismatches == 0)
    record("汇总表年度数", "9", str(len(dist_rows)), len(dist_rows) == 9)

    total = dist_rows["合计"]
    report = [
        "# wage_fix_v2 独立复核报告",
        "",
        f"结论：通过。{len(checks)}项检查全部通过。v2 在 v1 基础上只做了一件事——把“面议”占位值 888,888 置为缺失，"
        "未改动其他任何工资数值。",
        "",
        "## 一、检查项",
        "",
        "|检查项|预期|实际|结果|",
        "|---|---|---|---|",
    ]
    report += [f"|{n}|{e}|{a}|{s}|" for n, e, a, s in checks]
    report += [
        "",
        "## 二、修正与缺失",
        "",
        "|年份|记录数|修正（÷12/÷10）|置缺失|有效记录|平均月薪|中位月薪|>10万占比|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in [str(y) for y in range(2018, 2026)]:
        row = dist_rows[year]
        report.append(
            f"|{year}|{int(row['rows']):,}|{int(row['divided']):,}|{int(row['set_missing']):,}|"
            f"{int(row['valid_rows']):,}|{float(row['mean_wage']):,.0f}|{float(row['median_wage']):,.0f}|"
            f"{float(row['share_over_100k'])*100:.3f}%|"
        )
    report.append(
        f"|合计|{int(total['rows']):,}|{int(total['divided']):,}|{int(total['set_missing']):,}|"
        f"{int(total['valid_rows']):,}|{float(total['mean_wage']):,.0f}|{float(total['median_wage']):,.0f}|"
        f"{float(total['share_over_100k'])*100:.3f}%|"
    )
    report += [
        "",
        "## 三、口径说明",
        "",
        "- `wage_fix_flag=2` 的46条记录：工资与对数工资均为缺失，原值 888,888 仍保留在 `wage_mid_orig`；",
        "- 这46条全部来自 2018 年平台38，岗位从门卫到装配总监，888,888 是平台表示“薪资面议”的占位值；",
        "- 缺失不是删除：记录仍留在表里，做回归时被自动剔除，样本量从 5,235,461 变为 5,235,415；",
        "- 其他所有记录与 `wage_fix_v1` 逐条完全一致。",
        "",
        "## 四、复现",
        "",
        "```powershell",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/43_build_wage_fix_v2.py",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/44_validate_wage_fix_v2.py",
        "```",
        "",
    ]
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"WAGE_FIX_V2_VALIDATION={REPORT_PATH}")
    print("WAGE_FIX_V2_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
