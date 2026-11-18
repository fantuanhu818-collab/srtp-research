"""校验2022年V4.2候选版只补充Z99，不改动V4.1既有分类。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v042_2022_validation_summary.csv"
REPORT_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v042_2022_validation.md"
REVIEW_PATH = PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118" / "occupation_v042_2022_manual_review_sample_400.csv"


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    valid_codes = set(json.loads(BASE_RULE_PATH.read_text(encoding="utf-8"))["occupation_names"])
    old_path = Path(storage["features_root"]) / "occupation_v0.4.1" / "jobs_2022_occupation_v0.4.1.parquet"
    new_path = Path(storage["features_root"]) / "occupation_v0.4.2_candidate" / "jobs_2022_occupation_v0.4.2_candidate.parquet"
    columns = ["source_record_id", "occupation_id", "occupation_l1"]
    old = pq.read_table(old_path, columns=columns).to_pandas().rename(columns={
        "occupation_id": "old_id", "occupation_l1": "old_l1"
    })
    new = pq.read_table(new_path, columns=columns).to_pandas().rename(columns={
        "occupation_id": "new_id", "occupation_l1": "new_l1"
    })
    old["source_record_id"] = old["source_record_id"].astype(str)
    new["source_record_id"] = new["source_record_id"].astype(str)
    joined = old.merge(new, on="source_record_id", how="outer", validate="one_to_one", indicator=True)

    existing_mask = joined["old_id"].ne("Z99")
    changed_existing = int((joined.loc[existing_mask, "old_id"] != joined.loc[existing_mask, "new_id"]).sum())
    illegal_new = int((~joined["new_id"].isin(valid_codes)).sum())
    l1_mismatch = int((joined["new_id"].str[0] != joined["new_l1"]).sum())
    newly_classified = int((joined["old_id"].eq("Z99") & joined["new_id"].ne("Z99")).sum())
    review = pd.read_csv(REVIEW_PATH, encoding="utf-8-sig", dtype=str)
    result = {
        "old_rows": len(old),
        "new_rows": len(new),
        "joined_rows": len(joined),
        "id_join_failures": int(joined["_merge"].ne("both").sum()),
        "duplicate_old_ids": int(old["source_record_id"].duplicated().sum()),
        "duplicate_new_ids": int(new["source_record_id"].duplicated().sum()),
        "changed_existing_v041_classifications": changed_existing,
        "newly_classified_from_v041_z99": newly_classified,
        "illegal_new_codes": illegal_new,
        "l1_code_mismatches": l1_mismatch,
        "review_sample_rows": len(review),
        "review_sample_unique_ids": review["source_record_id"].nunique(),
    }
    passed = (
        result["old_rows"] == result["new_rows"] == result["joined_rows"]
        and result["id_join_failures"] == 0
        and result["duplicate_old_ids"] == 0
        and result["duplicate_new_ids"] == 0
        and changed_existing == 0
        and illegal_new == 0
        and l1_mismatch == 0
        and result["review_sample_rows"] == result["review_sample_unique_ids"] == 400
    )
    result["passed"] = passed
    pd.DataFrame([result]).to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    REPORT_PATH.write_text(f"""# occupation V4.2 2022年候选版校验

- 行数：V4.1与V4.2候选版均为{len(old):,}条；
- 主键连接失败：{result['id_join_failures']}条；
- V4.1原有非Z99分类被修改：{changed_existing}条；
- 从V4.1的Z99新增分类：{newly_classified:,}条；
- 非法职业代码：{illegal_new}条；
- 一级代码不一致：{l1_mismatch}条；
- 人工复核样本：{len(review)}条，唯一ID {result['review_sample_unique_ids']}条；
- 总体验证：{'通过' if passed else '未通过'}。

本校验只证明数据结构和“只补Z99”的安全边界成立，不代表新增职业分类已经达到准确率门槛。
""", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
