"""扫描工资异常：确认除了已修正的三组之外，是否还有成批的单位/量级错误。

两类可疑形态：
A. 高段集中：某“年份×平台”里 月薪≥6万 的占比≥5%。年薪误录、量级放大都会落在这里。
B. 低段集中却没有高值：某“年份×平台”里 2.5万—6万 占比≥10%、同时 ≥6万 占比<5%。
   这类错误发生在“年薪只有3—6万”的低薪广告上，不会出现>10万的记录，只看>10万会漏掉。

输出：outputs/qc/wage_fix_v1_anomaly_scan.csv
每个命中单元的处置结论写在 SOURCE_NOTES 里，人工核查后维护。
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
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "qc" / "wage_fix_v1_anomaly_scan.csv"

MIN_ROWS = 1_000
HIGH_BAND_SHARE = 0.05
MID_BAND_LOW_SHARE = 0.10
MID_BAND_COVERED_SHARE = 0.05

# 人工核查结论（2026-11-19，A线）：命中但确认是真实高薪的平台
SOURCE_NOTES = {
    "平台22": "真实高薪：管理层岗位池，取值集中在25000/50000/100000分档，岗位为总监、经理、架构师",
    "平台13": "真实高薪：技术岗位池，java/算法/产品经理为主，各年≥2.5万占比9%—19%，跨年稳定",
    "平台10": "真实高薪：技术岗位池（算法工程师、大数据、Python高级），高段相对低段配对倍数2.4，属正常职级差",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    rules = load_json(RULES_PATH)["rules"]
    cleaned_glob = str(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet").replace("\\", "/")
    covered = {(int(rule["year"]), rule["platform"]): rule["rule_id"] for rule in rules}

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    cells = con.execute(
        f"""
        SELECT 招聘发布年份 AS y, 来源 AS p, count(*) AS n,
               count(*) FILTER (WHERE 月薪代表值 >= 25000 AND 月薪代表值 < 60000) AS mid_band,
               count(*) FILTER (WHERE 月薪代表值 >= 60000) AS high_band,
               median(月薪代表值) AS med
        FROM read_parquet('{cleaned_glob}')
        GROUP BY 1, 2
        HAVING count(*) >= {MIN_ROWS}
        """
    ).fetchall()

    rows = []
    for y, p, n, mid_band, high_band, med in cells:
        mid_share = mid_band / n
        high_share = high_band / n
        flagged = high_share >= HIGH_BAND_SHARE or (
            mid_share >= MID_BAND_LOW_SHARE and high_share < MID_BAND_COVERED_SHARE
        )
        if not flagged:
            continue
        rule_id = covered.get((int(y), p))
        if rule_id:
            status = "已由修正规则覆盖"
            note = f"规则{rule_id}"
        elif p in SOURCE_NOTES:
            status = "真实高薪，无需修正"
            note = SOURCE_NOTES[p]
        else:
            status = "待人工确认"
            note = "占比异常但缺乏配对或跨年证据，暂不修正"
        rows.append(
            {
                "year": int(y),
                "platform": p,
                "rows": int(n),
                "share_25k_60k": round(mid_share, 4),
                "share_60k_plus": round(high_share, 4),
                "median_wage": round(float(med), 1),
                "pattern": "高段集中" if high_share >= HIGH_BAND_SHARE else "低段集中且无高值",
                "status": status,
                "note": note,
            }
        )

    rows.sort(key=lambda r: (-r["share_60k_plus"], -r["rows"]))
    if not rows:
        rows = [{"year": "", "platform": "", "rows": 0, "share_25k_60k": 0, "share_60k_plus": 0,
                 "median_wage": 0, "pattern": "", "status": "无命中", "note": ""}]
    with open(OUTPUT_PATH, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    pending = [r for r in rows if r["status"] == "待人工确认"]
    print(f"命中单元：{len(rows)} 个，其中待人工确认 {len(pending)} 个")
    for r in rows:
        print(f"  {r['year']} {r['platform']:<8} n={r['rows']:>8,} 25-60k={r['share_25k_60k']*100:>5.1f}% "
              f"60k+={r['share_60k_plus']*100:>5.1f}% -> {r['status']}")
    print(f"WAGE_FIX_V1_ANOMALY_SCAN={OUTPUT_PATH}")
    print("WAGE_FIX_V1_SCAN_GATE=PASS" if not pending else "WAGE_FIX_V1_SCAN_GATE=REVIEW")
    return 0 if not pending else 2


if __name__ == "__main__":
    raise SystemExit(main())
