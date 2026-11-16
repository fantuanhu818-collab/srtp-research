"""独立验证v0.3的2022年粗职业分类试运行输出。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
EXPECTED_ROWS = 328_548
REPORT_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v03_2022_validation.md"


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    output_path = Path(storage["features_root"]) / "occupation_pilot_v0.3" / "jobs_2022_occupation_v0.3.parquet"
    output = pq.read_table(output_path).to_pandas()
    rules = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    valid_ids = set(rules["occupation_names"])
    required = {
        "source_record_id", "occupation_l1", "occupation_id", "occupation_name", "occupation_method",
        "occupation_score_top1", "occupation_score_top2", "occupation_score_margin", "occupation_confidence",
        "occupation_status", "occupation_review_flag", "legacy_occupation_id", "legacy_rule_id",
    }
    missing = required - set(output.columns)
    if missing:
        raise RuntimeError(f"v0.3输出缺少字段：{sorted(missing)}")
    if len(output) != EXPECTED_ROWS or output["source_record_id"].duplicated().any():
        raise RuntimeError("v0.3输出行数或来源记录ID异常")
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    if set(output["source_record_id"]) != core_ids:
        raise RuntimeError("v0.3输出与confirmed_core_v2来源记录ID不一致")
    if not set(output["occupation_id"].astype(str)).issubset(valid_ids):
        raise RuntimeError("v0.3存在未知职业代码")
    if not (output["occupation_l1"].astype(str) == output["occupation_id"].astype(str).str[0]).all():
        raise RuntimeError("职业大类代码与职业组代码不一致")

    legacy_classified = output["legacy_occupation_id"].ne("Z99")
    if not output.loc[legacy_classified, "occupation_id"].eq(output.loc[legacy_classified, "legacy_occupation_id"]).all():
        raise RuntimeError("v0.3错误改写了原关键词规则已分类记录")
    exact = output["occupation_method"].eq("exact_anchor")
    if not (output.loc[exact, "occupation_score_top1"].eq(100).all() and output.loc[exact, "occupation_id"].ne("Z99").all()):
        raise RuntimeError("精确词典匹配的分数或职业组异常")
    fuzzy = output["occupation_method"].eq("fuzzy_anchor")
    if not (
        output.loc[fuzzy, "occupation_id"].ne("Z99").all()
        and output.loc[fuzzy, "occupation_score_top1"].ge(90).all()
        and output.loc[fuzzy, "occupation_score_margin"].ge(5).all()
        and output.loc[fuzzy, "legacy_occupation_id"].eq("Z99").all()
    ):
        raise RuntimeError("高分模糊匹配未满足阈值或不应覆盖旧规则")
    unclassified = output["occupation_method"].eq("unclassified")
    if not output.loc[unclassified, "occupation_id"].eq("Z99").all():
        raise RuntimeError("未分类记录职业代码异常")
    if output.loc[fuzzy, "occupation_review_flag"].ne(1).any():
        raise RuntimeError("高分模糊匹配未标记人工复核")

    total = len(output)
    classified = int(output["occupation_id"].ne("Z99").sum())
    legacy_count = int(legacy_classified.sum())
    exact_count = int(exact.sum())
    fuzzy_count = int(fuzzy.sum())
    report = f"""# 2022年粗职业分类试运行验证 v0.3

结论：通过。此验证只确认程序输出的主键、分类代码和阈值逻辑正确；不替代人工对职业含义的准确性复核。

- 输出记录数：{total:,}，与2022年`confirmed_core_v2`一一对应；
- 最终分类记录：{classified:,}，覆盖率{classified / total:.2%}；
- 原关键词规则已分类记录：{legacy_count:,}，在v0.3中全部保留原职业组；
- 词典精确补漏：{exact_count:,}条；
- 高分模糊补漏：{fuzzy_count:,}条，均满足分数≥90且前两名分差≥5，并已标记人工复核；
- 所有未分类记录均为`Z99`；所有职业组代码均在37组规则表内。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"CLASSIFIED={classified}")
    print(f"CLASSIFIED_SHARE={classified / total:.6f}")
    print(f"EXACT_ANCHOR={exact_count}")
    print(f"FUZZY_ANCHOR={fuzzy_count}")
    print("OCCUPATION_V03_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
