"""独立验证2022年职业大典v0.2试运行输出。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
DICTIONARY_PATH = PROJECT_ROOT / "config" / "occupation_dictionary_2022_official.csv"
HIERARCHY_PATH = PROJECT_ROOT / "config" / "occupation_hierarchy_2022_official.csv"
ALIAS_PATH = PROJECT_ROOT / "config" / "occupation_aliases_v0.2.csv"
FALLBACK_PATH = PROJECT_ROOT / "config" / "occupation_legacy_group_to_small_v0.2.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "occupation_v02_2022_summary.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_v02_2022_distribution.csv"
REVIEW_PATH = QC_ROOT / "occupation_v02_2022_review_sample.csv"
REPORT_PATH = QC_ROOT / "occupation_v02_2022_validation.md"
EXPECTED_ROWS = 328_548
UNCLASSIFIED = "8-00-00"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    storage = load_json(STORAGE_PATH)
    output_root = Path(storage["features_root"]) / "occupation_pilot_v0.2"
    output_path = output_root / "jobs_2022_occupation_v0.2.parquet"
    manifest_path = output_root / "manifest_2022.json"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"

    dictionary = pd.read_csv(DICTIONARY_PATH, dtype="string").fillna("")
    hierarchy = pd.read_csv(HIERARCHY_PATH, dtype={"occupation_level": "int8", "occupation_code": "string"}).fillna("")
    aliases = pd.read_csv(ALIAS_PATH, dtype="string").fillna("")
    fallback = pd.read_csv(FALLBACK_PATH, dtype="string").fillna("")
    require(len(dictionary) == 1_639, "职业大典细类不是1,639个")
    require(dictionary["occupation_fine_code"].is_unique, "职业细类代码不唯一")
    hierarchy_counts = hierarchy.groupby("occupation_level").size().to_dict()
    require(hierarchy_counts == {1: 8, 2: 79, 3: 450}, f"职业层级数量异常：{hierarchy_counts}")
    require(hierarchy.loc[(hierarchy["occupation_level"] == 3) & hierarchy["occupation_code"].ne(UNCLASSIFIED), "occupation_code"].nunique() == 449, "实质职业小类不是449个")
    require(len(aliases) >= 2_700 and aliases["alias_normalized"].is_unique, "别名表数量或唯一性异常")
    require(fallback["legacy_occupation_id"].is_unique, "旧职业组兜底表编号不唯一")

    table = pq.read_table(output_path)
    output = table.to_pandas()
    require(len(output) == EXPECTED_ROWS, "试运行输出行数异常")
    require(output["source_record_id"].is_unique, "试运行输出来源记录ID不唯一")
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    require(set(output["source_record_id"].astype(str)) == core_ids, "试运行输出与confirmed_core_v2来源记录ID不一致")

    small_reference = dictionary.drop_duplicates("occupation_small_code").set_index("occupation_small_code")
    valid_small = set(small_reference.index)
    require(set(output["occupation_id"].dropna().astype(str)) <= valid_small, "输出存在职业大典之外的小类代码")
    require(output["occupation_id"].astype(str).eq(output["occupation_small_code"].astype(str)).all(), "occupation_id与小类代码不一致")
    require(set(output["occupation_id_high_confidence"].dropna().astype(str)) <= valid_small, "高置信度职业代码不在职业大典中")

    classified = output["occupation_id"].astype(str).ne(UNCLASSIFIED)
    high_classified = output["occupation_id_high_confidence"].astype(str).ne(UNCLASSIFIED)
    require((~high_classified | classified).all(), "高置信度分类不应超出扩展分类")
    require(output.loc[high_classified, "occupation_id_high_confidence"].astype(str).eq(output.loc[high_classified, "occupation_id"].astype(str)).all(), "高置信度代码与扩展代码不一致")

    exact = output["occupation_status"].astype(str).eq("exact_accepted")
    fuzzy = output["occupation_status"].astype(str).eq("fuzzy_high_accepted")
    fallback_mask = output["occupation_status"].astype(str).eq("legacy_group_fallback")
    require(output.loc[exact, "occupation_score_top1"].eq(100).all(), "完全匹配分数不是100")
    require((output.loc[fuzzy, "occupation_score_top1"] >= 90).all(), "高分模糊匹配低于90分")
    require((output.loc[fuzzy, "occupation_score_margin"] >= 5).all(), "高分模糊匹配前两名分差不足5分")
    require(output.loc[exact | fuzzy, "occupation_review_flag"].eq(0).all(), "高置信度结果被错误标记为复核")
    require(output.loc[fallback_mask, "occupation_match_method"].astype(str).eq("legacy_group_fallback").all(), "兜底状态和方法不一致")
    require(output.loc[fallback_mask, "occupation_review_flag"].eq(1).all(), "中置信度兜底结果必须复核")
    require(output.loc[fallback_mask, "occupation_fine_code"].fillna("").astype(str).eq("").all(), "小类兜底不得伪造职业细类")
    require(output.loc[fallback_mask, "occupation_id_high_confidence"].astype(str).eq(UNCLASSIFIED).all(), "兜底结果不应进入高置信度变量")
    require(set(output.loc[fallback_mask, "legacy_occupation_id"].astype(str)) <= set(fallback["legacy_occupation_id"].astype(str)), "出现未配置的旧职业组兜底")

    unclassified = ~classified
    require(output.loc[unclassified, "occupation_small_name"].astype(str).eq("不便分类的其他从业人员").all(), "未分类代码和名称不一致")
    require(output["occupation_score_top1"].between(0, 100, inclusive="both").all(), "第一名分数越界")
    require(output["occupation_score_top2"].between(0, 100, inclusive="both").all(), "第二名分数越界")
    require((output["occupation_score_margin"] >= -0.001).all(), "匹配分差为负")

    for code, group in output.groupby("occupation_id", sort=False):
        reference = small_reference.loc[str(code)]
        require(group["occupation_small_name"].astype(str).eq(str(reference["occupation_small_name"])).all(), f"小类名称不一致：{code}")
        require(group["occupation_middle_code"].astype(str).eq(str(reference["occupation_middle_code"])).all(), f"中类代码不一致：{code}")
        require(group["occupation_major_code"].astype(str).eq(str(reference["occupation_major_code"])).all(), f"大类代码不一致：{code}")

    summary = pd.read_csv(SUMMARY_PATH, dtype={"dimension": "string", "value": "string", "count": "int64"})
    status_summary = summary.loc[summary["dimension"].eq("occupation_status")].set_index("value")["count"].to_dict()
    require(sum(status_summary.values()) == EXPECTED_ROWS, "状态汇总未与总行数闭合")
    for status, count in output["occupation_status"].value_counts().items():
        require(status_summary.get(str(status)) == int(count), f"状态汇总不一致：{status}")

    distribution = pd.read_csv(DISTRIBUTION_PATH)
    require(int(distribution["count"].sum()) == EXPECTED_ROWS, "职业分布未与总行数闭合")
    review = pd.read_csv(REVIEW_PATH, dtype="string")
    require(len(review) == 800 and review["source_record_id"].is_unique, "人工复核样本不是800条唯一记录")

    manifest = load_json(manifest_path)
    require(manifest["rows"] == EXPECTED_ROWS, "manifest行数异常")
    require(manifest["classified_rows"] == int(classified.sum()), "manifest扩展分类数不一致")
    require(manifest["high_confidence_classified_rows"] == int(high_classified.sum()), "manifest高置信度分类数不一致")

    classified_count = int(classified.sum())
    high_count = int(high_classified.sum())
    fallback_count = int(fallback_mask.sum())
    report = f"""# 2022年职业大典v0.2试运行独立验证

结论：PASS

## 验证结果

- 输出行数：{len(output):,}，与2022年`confirmed_core_v2`来源记录ID一一对应；
- `occupation_id`全部为职业大典小类代码，且与小类、中类、大类名称和代码一致；
- 扩展版已分类：{classified_count:,}条，占{classified_count / len(output):.2%}；
- 高置信度已分类：{high_count:,}条，占{high_count / len(output):.2%}；
- 旧职业组小类兜底：{fallback_count:,}条，均标记为中置信度和待复核，未伪造职业细类；
- 完全匹配分数、高分模糊匹配阈值、前两名分差和审核标记均符合方案；
- 汇总表、职业分布和manifest与Parquet主表闭合；
- 800条分层人工复核样本已生成且主键唯一。

## 尚未完成的验证

本报告验证数据结构和程序规则，不代表人工分类准确率。正式并入回归底表前，仍需填写分层复核样本并计算小类准确率；中置信度兜底结果应单独报告准确率。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"ROWS={len(output)}")
    print(f"CLASSIFIED={classified_count}")
    print(f"HIGH_CONFIDENCE={high_count}")
    print(f"LEGACY_FALLBACK={fallback_count}")
    print("OCCUPATION_V02_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
