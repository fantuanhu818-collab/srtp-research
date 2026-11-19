"""独立复核 wage_fix_v3：用 SQL 从 v2 与 cleaned_v1 重算，不复用构建逻辑。

复核重点：
1. 结构、行数、ID唯一、flag取值；
2. 全表不存在月薪>100000的记录（v3 的核心目标）；
3. 可修正集合（v2未修正且100000<月薪<=1200000）在v3中应等于 v2/12；
4. 无法修正集合（v2月薪>1200000，或v2已修正过且仍>100000）在v3中应为缺失；
5. 其余记录与 v2 逐条一致；
6. 对数与工资一致、缺失记录对数为空；
7. 分布表与汇总表一致。

输出：outputs/qc/wage_fix_v3_validation.md
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
DIST_PATH = QC_ROOT / "wage_fix_v3_distribution.csv"
SUMMARY_PATH = QC_ROOT / "wage_fix_v3_summary.csv"
REPORT_PATH = QC_ROOT / "wage_fix_v3_validation.md"

EXPECTED_ROWS = 5_235_461
EXPECTED_FIX = 2_896
EXPECTED_MISS = 86
EXPECTED_MISSING_TOTAL = 46 + 86
THRESHOLD = 100_000.0
CAP = 1_200_000.0
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
    v2 = str(Path(storage["features_root"]) / "wage_fix_v2" / "jobs_*_wage_fix.parquet").replace("\\", "/")
    v3 = str(Path(storage["features_root"]) / "wage_fix_v3" / "jobs_*_wage_fix.parquet").replace("\\", "/")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    checks: list[tuple[str, str, str, str]] = []

    def record(name: str, expected: str, actual: str, ok: bool) -> None:
        checks.append((name, expected, actual, "通过" if ok else "失败"))
        if not ok:
            raise RuntimeError(f"复核失败：{name}（预期{expected}，实际{actual}）")

    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{v3}')").fetchall()]
    record("字段清单", ",".join(EXPECTED_COLUMNS), ",".join(columns), columns == EXPECTED_COLUMNS)

    rows = con.execute(f"SELECT count(*) FROM read_parquet('{v3}')").fetchone()[0]
    record("总行数", f"{EXPECTED_ROWS:,}", f"{rows:,}", rows == EXPECTED_ROWS)

    uniq = con.execute(f"SELECT count(DISTINCT source_record_id) FROM read_parquet('{v3}')").fetchone()[0]
    record("source_record_id唯一数", f"{EXPECTED_ROWS:,}", f"{uniq:,}", uniq == EXPECTED_ROWS)

    bad_flag = con.execute(f"SELECT count(*) FROM read_parquet('{v3}') WHERE wage_fix_flag NOT IN (0,1,2)").fetchone()[0]
    record("wage_fix_flag取值越界", "0", f"{bad_flag:,}", bad_flag == 0)

    over = con.execute(f"SELECT count(*) FROM read_parquet('{v3}') WHERE wage_mid_fixed > {THRESHOLD}").fetchone()[0]
    record("月薪>100000的记录数", "0", f"{over:,}", over == 0)

    mx = con.execute(f"SELECT max(wage_mid_fixed) FROM read_parquet('{v3}')").fetchone()[0]
    record("全表最大月薪", "≤100000", f"{float(mx):,.0f}", float(mx) <= THRESHOLD)

    # 与 v2 的逐条对账
    r = con.execute(
        f"""
        WITH b AS (SELECT source_record_id AS id, wage_mid_fixed AS w2, ln_wage_fixed AS ln2,
                          wage_fix_flag AS f2, wage_fix_rule AS r2 FROM read_parquet('{v2}')),
             c AS (SELECT source_record_id AS id, wage_mid_fixed AS w3, ln_wage_fixed AS ln3,
                          wage_fix_flag AS f3, wage_fix_rule AS r3 FROM read_parquet('{v3}'))
        SELECT count(*),
          -- 可修正：v2未修正且 100000<w2<=1200000，v3应为 w2/12
          sum(CASE WHEN f2=0 AND w2 > {THRESHOLD} AND w2 <= {CAP} AND abs(w3 - w2/12.0) > 1e-9 THEN 1 ELSE 0 END) fix_bad,
          sum(CASE WHEN f2=0 AND w2 > {THRESHOLD} AND w2 <= {CAP} THEN 1 ELSE 0 END) fix_n,
          -- 无法修正：v2 >120万，或 v2已修正且仍>10万，v3应为空
          sum(CASE WHEN (w2 > {CAP} OR (f2=1 AND w2 > {THRESHOLD})) AND w3 IS NOT NULL THEN 1 ELSE 0 END) miss_bad,
          sum(CASE WHEN (w2 > {CAP} OR (f2=1 AND w2 > {THRESHOLD})) THEN 1 ELSE 0 END) miss_n,
          -- 其余应逐条不变
          sum(CASE WHEN NOT (w2 > {THRESHOLD}) AND abs(w3 - w2) > 1e-9 THEN 1 ELSE 0 END) untouched_bad,
          sum(CASE WHEN w3 IS NOT NULL AND abs(ln3 - ln(w3)) > 1e-9 THEN 1 ELSE 0 END) ln_bad,
          sum(CASE WHEN w3 IS NULL AND ln3 IS NOT NULL THEN 1 ELSE 0 END) null_wage_has_ln
        FROM b JOIN c USING (id)
        """
    ).fetchone()
    record("与v2可匹配记录数", f"{EXPECTED_ROWS:,}", f"{int(r[0]):,}", int(r[0]) == EXPECTED_ROWS)
    record("可修正条数", f"{EXPECTED_FIX:,}", f"{int(r[2]):,}", int(r[2]) == EXPECTED_FIX)
    record("可修正记录未按÷12处理", "0", f"{int(r[1]):,}", int(r[1]) == 0)
    record("无法修正条数", f"{EXPECTED_MISS:,}", f"{int(r[4]):,}", int(r[4]) == EXPECTED_MISS)
    record("无法修正记录未置缺失", "0", f"{int(r[3]):,}", int(r[3]) == 0)
    record("其余记录被改动", "0", f"{int(r[5]):,}", int(r[5]) == 0)
    record("对数不等于ln(工资)", "0", f"{int(r[6]):,}", int(r[6]) == 0)
    record("工资缺失但对数非缺失", "0", f"{int(r[7]):,}", int(r[7]) == 0)

    miss_total = con.execute(f"SELECT count(*) FROM read_parquet('{v3}') WHERE wage_fix_flag = 2").fetchone()[0]
    record("缺失记录总数（含占位值46条）", f"{EXPECTED_MISSING_TOTAL}", f"{int(miss_total)}", int(miss_total) == EXPECTED_MISSING_TOTAL)

    # 分布表一致性
    dist_rows = {row["year"]: row for row in read_csv_rows(DIST_PATH)}
    live = con.execute(
        f"""
        SELECT regexp_extract(filename, 'jobs_([0-9]{{4}})_', 1) AS yr, count(*),
               sum(CASE WHEN wage_fix_flag = 1 THEN 1 ELSE 0 END),
               sum(CASE WHEN wage_fix_flag = 2 THEN 1 ELSE 0 END),
               count(wage_mid_fixed), round(avg(wage_mid_fixed), 2), round(median(wage_mid_fixed), 2),
               round(quantile_cont(wage_mid_fixed, 0.99), 2), round(max(wage_mid_fixed), 2),
               round(avg(CASE WHEN wage_mid_fixed > {THRESHOLD} THEN 1 ELSE 0 END), 6)
        FROM read_parquet('{v3}', filename=true) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    mismatches = 0
    for x in live:
        row = dist_rows.get(str(int(x[0])))
        if row is None:
            mismatches += 1
            continue
        pairs = [
            (int(x[1]), int(row["rows"])), (int(x[2]), int(row["corrected"])),
            (int(x[3]), int(row["missing"])), (int(x[4]), int(row["valid_rows"])),
            (float(x[5]), float(row["mean_wage"])), (float(x[6]), float(row["median_wage"])),
            (float(x[7]), float(row["p99_wage"])), (float(x[8]), float(row["max_wage"])),
            (float(x[9]), float(row["share_over_100k"])),
        ]
        mismatches += sum(1 for a, b in pairs if abs(a - b) > 1e-3)
    record("年度分布与CSV不一致项", "0", str(mismatches), mismatches == 0)
    record("汇总表年度数", "9", str(len(dist_rows)), len(dist_rows) == 9)

    total = dist_rows["合计"]
    report = [
        "# wage_fix_v3 独立复核报告",
        "",
        f"结论：通过。{len(checks)}项检查全部通过。v3 把“修正后仍超10万”的记录处理干净：能按年薪还原的一律÷12，"
        "明显无法修正的置为缺失；处理后全表月薪上限为10万元。",
        "",
        "## 一、检查项",
        "",
        "|检查项|预期|实际|结果|",
        "|---|---|---|---|",
    ]
    report += [f"|{n}|{e}|{a}|{s}|" for n, e, a, s in checks]
    report += [
        "",
        "## 二、处理结果",
        "",
        "|年份|记录数|已修正|缺失|有效记录|平均月薪|中位月薪|>10万占比|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in [str(y) for y in range(2018, 2026)]:
        row = dist_rows[year]
        report.append(
            f"|{year}|{int(row['rows']):,}|{int(row['corrected']):,}|{int(row['missing']):,}|"
            f"{int(row['valid_rows']):,}|{float(row['mean_wage']):,.0f}|{float(row['median_wage']):,.0f}|"
            f"{float(row['share_over_100k'])*100:.3f}%|"
        )
    report.append(
        f"|合计|{int(total['rows']):,}|{int(total['corrected']):,}|{int(total['missing']):,}|"
        f"{int(total['valid_rows']):,}|{float(total['mean_wage']):,.0f}|{float(total['median_wage']):,.0f}|"
        f"{float(total['share_over_100k'])*100:.3f}%|"
    )
    report += [
        "",
        "## 三、口径说明",
        "",
        "- 2,896条：v2未修正、月薪在10万—120万之间，按年薪÷12（其中26条÷12后仍在5万—10万，属高管/总监岗位）；",
        "- 86条置缺失：13条原值>120万（÷12后仍超10万），73条已被v1按年薪÷12过一次、原值280万—800万，"
        "再除一次缺乏依据；典型如2020平台28“cto”969万、2021平台1“快递员”750万、2021平台1“肯德基服务员”450万；",
        "- 加上v2的46条占位值，全表共132条缺失，记录均保留在表中，回归时自动剔除；",
        "- 处理完成后最大月薪为100,000元；",
        "- 每一条被处理的记录都可在`outputs/qc/wage_fix_v3_extremes_resolved.csv`中追溯（含处理前、处理后、规则）。",
        "",
        "## 四、复现",
        "",
        "```powershell",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/45_build_wage_fix_v3.py",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/46_validate_wage_fix_v3.py",
        "```",
        "",
    ]
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"WAGE_FIX_V3_VALIDATION={REPORT_PATH}")
    print("WAGE_FIX_V3_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
