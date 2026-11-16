"""独立验证2018—2025年v0.3全量职业特征。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
YEARS = list(range(2018, 2026))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
REPORT_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v03_all_years_validation.md"
EXPECTED_TOTAL = 5_235_398


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    valid_ids = set(rules["occupation_names"])
    root = Path(storage["features_root"]) / "occupation_v0.3"
    rows: list[dict] = []
    all_ids: set[str] = set()

    required = {
        "source_record_id", "occupation_l1", "occupation_id", "occupation_name",
        "occupation_method", "occupation_score_top1", "occupation_score_top2",
        "occupation_score_margin", "occupation_confidence", "occupation_status",
        "occupation_review_flag", "legacy_occupation_id", "occupation_version",
    }
    for year in YEARS:
        output_path = root / f"jobs_{year}_occupation_v0.3.parquet"
        core_path = Path(storage["features_root"]) / "confirmed_core_v2" / f"jobs_{year}_confirmed_core.parquet"
        output = pq.read_table(output_path).to_pandas()
        missing = required - set(output.columns)
        if missing:
            raise RuntimeError(f"{year}年职业特征缺少字段：{sorted(missing)}")
        if output["source_record_id"].duplicated().any():
            raise RuntimeError(f"{year}年职业特征来源记录ID重复")
        core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
        output_ids = set(output["source_record_id"].astype(str))
        if output_ids != core_ids:
            raise RuntimeError(f"{year}年职业特征未与confirmed_core_v2一一对应")
        if all_ids.intersection(output_ids):
            raise RuntimeError(f"{year}年与其他年度存在重复来源记录ID")
        all_ids.update(output_ids)
        if not set(output["occupation_id"].astype(str)).issubset(valid_ids):
            raise RuntimeError(f"{year}年出现未知37组职业代码")
        if not output["occupation_l1"].astype(str).eq(output["occupation_id"].astype(str).str[0]).all():
            raise RuntimeError(f"{year}年职业大类与职业组代码不一致")

        legacy = output["legacy_occupation_id"].ne("Z99")
        if not output.loc[legacy, "occupation_id"].eq(output.loc[legacy, "legacy_occupation_id"]).all():
            raise RuntimeError(f"{year}年原关键词规则结果被后续匹配改写")
        exact = output["occupation_method"].eq("exact_anchor")
        if not (
            output.loc[exact, "occupation_id"].ne("Z99").all()
            and output.loc[exact, "occupation_score_top1"].eq(100).all()
            and output.loc[exact, "legacy_occupation_id"].eq("Z99").all()
        ):
            raise RuntimeError(f"{year}年词典精确匹配逻辑异常")
        fuzzy = output["occupation_method"].eq("fuzzy_anchor")
        if not (
            output.loc[fuzzy, "occupation_id"].ne("Z99").all()
            and output.loc[fuzzy, "occupation_score_top1"].ge(90).all()
            and output.loc[fuzzy, "occupation_score_margin"].ge(5).all()
            and output.loc[fuzzy, "legacy_occupation_id"].eq("Z99").all()
            and output.loc[fuzzy, "occupation_review_flag"].eq(1).all()
        ):
            raise RuntimeError(f"{year}年高分模糊匹配阈值或覆盖顺序异常")
        unclassified = output["occupation_method"].eq("unclassified")
        if not output.loc[unclassified, "occupation_id"].eq("Z99").all():
            raise RuntimeError(f"{year}年未分类记录代码异常")

        total = len(output)
        classified = int(output["occupation_id"].ne("Z99").sum())
        rows.append({
            "year": year, "records": total, "classified": classified,
            "classified_share": classified / total, "z99": total - classified,
            "exact_anchor": int(exact.sum()), "fuzzy_anchor": int(fuzzy.sum()),
        })

    if len(all_ids) != EXPECTED_TOTAL:
        raise RuntimeError(f"全量职业特征记录数异常：{len(all_ids):,}")

    # 2022年全量运行必须复现此前单年试运行的最终分类和匹配方法。
    full_2022 = pq.read_table(root / "jobs_2022_occupation_v0.3.parquet", columns=[
        "source_record_id", "occupation_id", "occupation_method", "occupation_status",
    ]).to_pandas().sort_values("source_record_id").reset_index(drop=True)
    pilot_2022 = pq.read_table(
        Path(storage["features_root"]) / "occupation_pilot_v0.3" / "jobs_2022_occupation_v0.3.parquet",
        columns=["source_record_id", "occupation_id", "occupation_method", "occupation_status"],
    ).to_pandas().sort_values("source_record_id").reset_index(drop=True)
    if not full_2022.equals(pilot_2022):
        differences = int(
            full_2022[["occupation_id", "occupation_method", "occupation_status"]]
            .ne(pilot_2022[["occupation_id", "occupation_method", "occupation_status"]]).any(axis=1).sum()
        )
        raise RuntimeError(f"2022年全量运行未复现单年试运行：{differences}条不同")

    annual = pd.DataFrame(rows)
    total = int(annual["records"].sum())
    classified = int(annual["classified"].sum())
    table_lines = [
        f"|{int(row.year)}|{int(row.records):,}|{int(row.classified):,}|{row.classified_share:.2%}|{int(row.z99):,}|{int(row.exact_anchor):,}|{int(row.fuzzy_anchor):,}|"
        for row in annual.itertuples(index=False)
    ]
    report = f"""# 2018—2025年粗职业分类全量验证 v0.3

结论：通过。全部职业特征与`confirmed_core_v2`逐年逐条对应，原关键词结果未被改写，精确匹配与模糊匹配均符合v0.3规则；2022年全量结果与单年试运行完全一致。

## 总体结果

- 总记录：{total:,}条；
- 已分类：{classified:,}条，覆盖率{classified / total:.2%}；
- `Z99`：{total - classified:,}条，占{1 - classified / total:.2%}；
- 词典精确补漏：{int(annual['exact_anchor'].sum()):,}条；
- 高分模糊补漏：{int(annual['fuzzy_anchor'].sum()):,}条；
- 2022年与单年试运行比较：完全一致。

|年份|记录数|已分类|覆盖率|Z99|精确补漏|模糊补漏|
|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(table_lines)}

本验证确认数据结构和执行逻辑，不替代项目成员对职业含义的人工准确性复核。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"TOTAL_ROWS={total}")
    print(f"CLASSIFIED={classified}")
    print(f"CLASSIFIED_SHARE={classified / total:.6f}")
    print("PILOT_2022_REPRODUCED=PASS")
    print("OCCUPATION_V03_ALL_YEARS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
