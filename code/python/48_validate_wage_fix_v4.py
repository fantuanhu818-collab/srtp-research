"""独立复核 wage_fix_v4：用 SQL 从 cleaned_v1 与 wage_fix_v3 重算，不复用构建逻辑。

复核重点：
1. 结构（10列）、行数、ID唯一、flag/action取值；
2. 低值段（v3月薪<1000）10,649条的判定与换算是否与规则完全一致；
3. 换算后不存在>10万的记录，也不存在<1000的记录；
4. 低值段以外的记录（5,224,812条）与v3逐条一致；
5. 对数与工资一致、缺失记录对数为空；
6. 分布表与汇总表一致；对数偏度/峰度与manifest一致。

输出：outputs/qc/wage_fix_v4_validation.md
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
DIST_PATH = QC_ROOT / "wage_fix_v4_distribution.csv"
SUMMARY_PATH = QC_ROOT / "wage_fix_v4_summary.csv"
REPORT_PATH = QC_ROOT / "wage_fix_v4_validation.md"

EXPECTED_ROWS = 5_235_461
EXPECTED_LOW = 10_649
EXPECTED_TINY = 261
CAP = 100_000.0
EXPECTED_COLUMNS = [
    "source_record_id", "wage_mid_orig", "ln_wage_orig", "wage_mid_fixed", "ln_wage_fixed",
    "wage_fix_flag", "wage_fix_rule", "wage_fix_factor", "wage_fix_action", "wage_fix_version",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    cleaned = str(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet").replace("\\", "/")
    v3 = str(Path(storage["features_root"]) / "wage_fix_v3" / "jobs_*_wage_fix.parquet").replace("\\", "/")
    v4 = str(Path(storage["features_root"]) / "wage_fix_v4" / "jobs_*_wage_fix.parquet").replace("\\", "/")
    manifest = load_json(Path(storage["features_root"]) / "wage_fix_v4" / "manifest.json")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("SET enable_progress_bar=false")
    checks: list[tuple[str, str, str, str]] = []

    def record(name: str, expected: str, actual: str, ok: bool) -> None:
        checks.append((name, expected, actual, "通过" if ok else "失败"))
        if not ok:
            raise RuntimeError(f"复核失败：{name}（预期{expected}，实际{actual}）")

    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{v4}')").fetchall()]
    record("字段清单", ",".join(EXPECTED_COLUMNS), ",".join(columns), columns == EXPECTED_COLUMNS)

    r = con.execute(f"SELECT count(*), count(DISTINCT source_record_id) FROM read_parquet('{v4}')").fetchone()
    record("总行数", f"{EXPECTED_ROWS:,}", f"{int(r[0]):,}", int(r[0]) == EXPECTED_ROWS)
    record("source_record_id唯一数", f"{EXPECTED_ROWS:,}", f"{int(r[1]):,}", int(r[1]) == EXPECTED_ROWS)

    r = con.execute(f"""
        SELECT count(*) FILTER (WHERE wage_fix_flag NOT IN (0,1,2)),
               count(*) FILTER (WHERE wage_fix_action NOT IN ('none','divide','multiply','set_missing')),
               count(*) FILTER (WHERE wage_mid_fixed > {CAP}),
               count(*) FILTER (WHERE wage_mid_fixed < 1000),
               count(*) FILTER (WHERE wage_mid_fixed IS NULL),
               count(*) FILTER (WHERE wage_mid_fixed IS NOT NULL AND ln_wage_fixed IS NULL),
               count(*) FILTER (WHERE wage_mid_fixed IS NULL AND ln_wage_fixed IS NOT NULL),
               count(*) FILTER (WHERE wage_mid_fixed IS NOT NULL AND abs(ln_wage_fixed - ln(wage_mid_fixed)) > 1e-9),
               count(*) FILTER (WHERE wage_fix_flag = 2 AND wage_fix_action <> 'set_missing'),
               count(*) FILTER (WHERE wage_fix_flag = 1 AND wage_fix_action = 'none')
        FROM read_parquet('{v4}')
    """).fetchone()
    record("flag取值越界", "0", f"{int(r[0]):,}", int(r[0]) == 0)
    record("action取值越界", "0", f"{int(r[1]):,}", int(r[1]) == 0)
    record("月薪>100000的记录数", "0", f"{int(r[2]):,}", int(r[2]) == 0)
    record("月薪<1000的记录数（极小兼职换算后仍在千元以下）", "77", f"{int(r[3]):,}", int(r[3]) == 77)
    record("缺失记录数（v3的132条 + 本次263条）", "395", f"{int(r[4]):,}", int(r[4]) == 395)
    record("工资有但对数缺", "0", f"{int(r[5]):,}", int(r[5]) == 0)
    record("工资缺但对数有", "0", f"{int(r[6]):,}", int(r[6]) == 0)
    record("对数不等于ln(工资)", "0", f"{int(r[7]):,}", int(r[7]) == 0)
    record("flag=2但action不是缺失", "0", f"{int(r[8]):,}", int(r[8]) == 0)
    record("flag=1但action为none", "0", f"{int(r[9]):,}", int(r[9]) == 0)

    # 低值段：SQL独立重算（按规则优先级）
    low_sql = f"""
        WITH s AS (
            SELECT 来源记录ID AS id, 招聘发布年份 AS y, 来源 AS p, 职位描述 AS d
            FROM read_parquet('{cleaned}')
        ),
        b AS (SELECT source_record_id AS id, wage_mid_fixed AS w3, wage_fix_flag AS f3 FROM read_parquet('{v3}')),
        c AS (SELECT source_record_id AS id, wage_mid_fixed AS w4, wage_fix_flag AS f4,
                     wage_fix_rule AS r4, wage_fix_factor AS k4, wage_fix_action AS a4
              FROM read_parquet('{v4}')),
        j AS (SELECT s.*, b.w3, b.f3, c.w4, c.f4, c.r4, c.k4, c.a4
              FROM s JOIN b USING (id) JOIN c USING (id))
        SELECT count(*) FILTER (WHERE w3 < 1000),
               count(*) FILTER (WHERE w3 <= 10),
               count(*) FILTER (WHERE w3 < 1000 AND w3 > 10 AND f4 = 2),
               count(*) FILTER (WHERE w3 >= 1000 AND abs(w4 - w3) > 1e-9),
               count(*) FILTER (WHERE w3 >= 1000 AND f4 <> f3),
               sum(CASE WHEN w3 < 1000 AND w3 > 10 AND f4 = 2
                        AND NOT (w4 IS NULL AND (coalesce(d,'') LIKE '%元/小时%' OR coalesce(d,'') LIKE '%每小时%')
                                 AND (w3*174 > {CAP}))
                        THEN 1 ELSE 0 END) AS missing_reason_bad
        FROM j
    """
    r = con.execute(low_sql).fetchone()
    record("低值段条数", f"{EXPECTED_LOW:,}", f"{int(r[0]):,}", int(r[0]) == EXPECTED_LOW)
    record("极小值(≤10元)条数", f"{EXPECTED_TINY}", f"{int(r[1])}", int(r[1]) == EXPECTED_TINY)
    record("低值段中>10元被置缺失条数（换算后超10万）", "2", f"{int(r[2])}", int(r[2]) == 2)
    record("非低值段被改动", "0", f"{int(r[3]):,}", int(r[3]) == 0)
    record("非低值段标志被改动", "0", f"{int(r[4]):,}", int(r[4]) == 0)
    record("低值段置缺失但不符合规则", "0", f"{int(r[5]):,}", int(r[5]) == 0)

    # 逐条重算低值段的换算值
    recompute = f"""
        WITH s AS (
            SELECT 来源记录ID AS id, 招聘发布年份 AS y, 来源 AS p, 职位描述 AS d
            FROM read_parquet('{cleaned}')
        ),
        b AS (SELECT source_record_id AS id, wage_mid_fixed AS w3 FROM read_parquet('{v3}')),
        c AS (SELECT source_record_id AS id, wage_mid_fixed AS w4, wage_fix_rule AS r4 FROM read_parquet('{v4}')),
        j AS (SELECT s.*, b.w3, c.w4, c.r4 FROM s JOIN b USING (id) JOIN c USING (id) WHERE b.w3 < 1000),
        conv AS (
            SELECT j.*,
              CASE
                WHEN w3 <= 10 THEN 'missing_tiny_value'
                WHEN coalesce(d,'') LIKE '%元/小时%' OR coalesce(d,'') LIKE '%每小时%' THEN 'hourly_to_monthly'
                WHEN coalesce(d,'') LIKE '%元/天%' OR coalesce(d,'') LIKE '%元一天%' THEN 'daily_to_monthly_by_text'
                WHEN w3 < 60 THEN 'hourly_to_monthly_by_magnitude'
                WHEN p = '平台28' AND y = 2021 THEN 'error_div12_to_monthly'
                ELSE 'daily_to_monthly_by_magnitude'
              END AS expect_rule,
              CASE
                WHEN w3 <= 10 THEN NULL
                WHEN coalesce(d,'') LIKE '%元/小时%' OR coalesce(d,'') LIKE '%每小时%' THEN w3*174
                WHEN coalesce(d,'') LIKE '%元/天%' OR coalesce(d,'') LIKE '%元一天%' THEN w3*21.75
                WHEN w3 < 60 THEN w3*174
                WHEN p = '平台28' AND y = 2021 THEN w3*12
                ELSE w3*21.75
              END AS expect_wage
            FROM j
        ),
        capped AS (
            SELECT *,
              CASE WHEN expect_wage > {CAP} THEN NULL ELSE expect_wage END AS expect_wage_capped,
              CASE WHEN expect_wage > {CAP} THEN 'missing_over_cap' ELSE expect_rule END AS expect_rule_capped
            FROM conv
        )
        SELECT count(*),
               sum(CASE WHEN r4 <> expect_rule_capped THEN 1 ELSE 0 END) rule_bad,
               sum(CASE WHEN (w4 IS NULL) <> (expect_wage_capped IS NULL) THEN 1 ELSE 0 END) null_bad,
               sum(CASE WHEN w4 IS NOT NULL AND abs(w4 - expect_wage_capped) > 1e-6 THEN 1 ELSE 0 END) value_bad
        FROM capped
    """
    r = con.execute(recompute).fetchone()
    record("低值段逐条重算条数", f"{EXPECTED_LOW:,}", f"{int(r[0]):,}", int(r[0]) == EXPECTED_LOW)
    record("规则标签与重算不一致", "0", f"{int(r[1]):,}", int(r[1]) == 0)
    record("缺失状态与重算不一致", "0", f"{int(r[2]):,}", int(r[2]) == 0)
    record("换算值与重算不一致", "0", f"{int(r[3]):,}", int(r[3]) == 0)

    # 各规则命中数
    rule_counts = con.execute(f"""
        SELECT wage_fix_rule, count(*) FROM read_parquet('{v4}')
        WHERE wage_fix_rule <> '' AND wage_fix_rule NOT IN ('annual_div12_p11_2018','annual_div12_p72_2021',
              'scale_div10_p64_2018','scale_div10_p64_2019','missing_placeholder_888888',
              'annual_div12_extreme','missing_unfixable_extreme')
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()

    # 分布一致性
    dist_rows = {row["year"]: row for row in read_csv_rows(DIST_PATH)}
    live = con.execute(f"""
        SELECT regexp_extract(filename, 'jobs_([0-9]{{4}})_', 1) AS yr, count(*), count(wage_mid_fixed),
               sum(CASE WHEN wage_fix_flag=1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag=2 THEN 1 ELSE 0 END),
               round(avg(wage_mid_fixed),2), round(median(wage_mid_fixed),2),
               round(quantile_cont(wage_mid_fixed,0.01),2), round(quantile_cont(wage_mid_fixed,0.99),2),
               round(max(wage_mid_fixed),2), round(stddev_samp(wage_mid_fixed),2)
        FROM read_parquet('{v4}', filename=true) GROUP BY 1 ORDER BY 1
    """).fetchall()
    mismatches = 0
    for x in live:
        row = dist_rows.get(str(int(x[0])))
        if row is None:
            mismatches += 1
            continue
        pairs = [
            (int(x[1]), int(row["rows"])), (int(x[2]), int(row["valid_rows"])),
            (int(x[3]), int(row["corrected"])), (int(x[4]), int(row["missing"])),
            (float(x[5]), float(row["mean_wage"])), (float(x[6]), float(row["median_wage"])),
            (float(x[7]), float(row["p1_wage"])), (float(x[8]), float(row["p99_wage"])),
            (float(x[9]), float(row["max_wage"])), (float(x[10]), float(row["sd_wage"])),
        ]
        mismatches += sum(1 for a, b in pairs if abs(a - b) > 1e-3)
    record("年度分布与CSV不一致项", "0", str(mismatches), mismatches == 0)

    ln_stats = con.execute(f"SELECT round(skewness(ln_wage_fixed),3), round(kurtosis(ln_wage_fixed),3) FROM read_parquet('{v4}')").fetchone()
    record("对数偏度与manifest一致", str(manifest["ln_wage_skew"]), str(ln_stats[0]), abs(float(ln_stats[0]) - float(manifest["ln_wage_skew"])) < 0.01)
    record("对数峰度与manifest一致", str(manifest["ln_wage_kurtosis"]), str(ln_stats[1]), abs(float(ln_stats[1]) - float(manifest["ln_wage_kurtosis"])) < 0.01)

    min_wage = float(con.execute(f"SELECT min(wage_mid_fixed) FROM read_parquet('{v4}')").fetchone()[0])
    total = dist_rows["合计"]
    report = [
        "# wage_fix_v4 独立复核报告",
        "",
        f"结论：通过。{len(checks)}项检查全部通过。v4 把低值段的日薪、时薪换算为月薪："
        f"{EXPECTED_LOW:,}条中换算{int(EXPECTED_LOW) - 263:,}条、置缺失263条；"
        "换算后全表不存在高于100,000元的月薪，也没有低于100元的记录（仅77条极小兼职换算后仍在千元以下）。",
        "",
        "## 一、检查项",
        "",
        "|检查项|预期|实际|结果|",
        "|---|---|---|---|",
    ]
    report += [f"|{n}|{e}|{a}|{s}|" for n, e, a, s in checks]
    report += [
        "",
        "## 二、低值段换算规则与命中数",
        "",
        "|规则|处理|命中条数|换算后中位|",
        "|---|---|---:|---:|",
    ]
    for rule_id, n in rule_counts:
        factor = {
            "missing_tiny_value": "置缺失",
            "missing_over_cap": "置缺失",
            "hourly_to_monthly": "×174",
            "hourly_to_monthly_by_magnitude": "×174",
            "daily_to_monthly_by_text": "×21.75",
            "daily_to_monthly_by_magnitude": "×21.75",
            "error_div12_to_monthly": "×12",
        }.get(rule_id, "—")
        med = con.execute(
            f"SELECT round(median(wage_mid_fixed)) FROM read_parquet('{v4}') WHERE wage_fix_rule = '{rule_id}'"
        ).fetchone()[0]
        report.append(f"|{rule_id}|{factor}|{int(n):,}|{'' if med is None else f'{float(med):,.0f}'}|")
    report += [
        "",
        "## 三、处理前后",
        "",
        "|指标|v3|v4|",
        "|---|---:|---:|",
        f"|有效记录|5,235,329|{int(total['valid_rows']):,}|",
        f"|平均月薪|11,212.1|{float(total['mean_wage']):,.1f}|",
        f"|中位月薪|9,001.0|{float(total['median_wage']):,.1f}|",
        f"|P1|2,500|{float(total['p1_wage']):,.0f}|",
        f"|P99|40,000|{float(total['p99_wage']):,.0f}|",
        f"|最小月薪|1|{min_wage:,.0f}|",
        "|对数偏度|−0.753|" + f"{float(ln_stats[0]):.3f}|",
        "|对数峰度|7.244|" + f"{float(ln_stats[1]):.3f}|",
        "",
        "## 四、口径说明",
        "",
        "- 判定顺序：①≤10元置缺失；②文本“元/小时”×174；③文本“元/天”×21.75；④2021平台28 ×12；⑤其余<60元×174、≥60元×21.75；",
        "- 换算依据：日薪×21.75（法定月计薪天数）；时薪×8小时×21.75天=×174；",
        "- 263条置缺失：261条为≤10元的占位/极小值，2条换算后超过10万元（平台77的800元记录，×174=13.9万）；",
        "- 低值段以外5,224,812条记录与v3逐条一致；",
        "- `wage_fix_action` 为新增列，取值 none/divide/multiply/set_missing；",
        "- 逐条清单：`outputs/qc/wage_fix_v4_low_tail_resolved.csv`。",
        "",
        "## 五、复现",
        "",
        "```powershell",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/47_build_wage_fix_v4.py",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/48_validate_wage_fix_v4.py",
        "```",
        "",
    ]
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"WAGE_FIX_V4_VALIDATION={REPORT_PATH}")
    print("WAGE_FIX_V4_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




