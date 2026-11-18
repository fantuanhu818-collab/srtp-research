"""生成未参与V4规则开发的300条独立人工验证样本。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from occupation_v04 import MANUAL_GOLD_PATH, build_classifier


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "occupation_v04_validation_20261118"
SAMPLE_PATH = OUTPUT_DIR / "occupation_v04_independent_validation_sample.csv"
SUMMARY_PATH = OUTPUT_DIR / "occupation_v04_independent_validation_summary.csv"
YEARS = range(2018, 2026)
TARGETS = {
    "context_rule": 80,
    "manual_alias": 60,
    "exact_anchor": 40,
    "keyword_rule": 50,
    "fuzzy_anchor": 40,
    "unclassified": 30,
}


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def take_balanced(frame: pd.DataFrame, target: int) -> pd.DataFrame:
    if len(frame) <= target:
        return frame.copy()
    per_year = max(1, math.ceil(target / len(YEARS)))
    chosen = []
    used: set[str] = set()
    for year in YEARS:
        part = frame.loc[frame["year"].eq(year)].sort_values("_hash").head(per_year)
        chosen.append(part)
        used.update(part["source_record_id"].tolist())
    result = pd.concat(chosen, ignore_index=True) if chosen else frame.head(0)
    if len(result) < target:
        extra = frame.loc[~frame["source_record_id"].isin(used)].sort_values("_hash").head(target - len(result))
        result = pd.concat([result, extra], ignore_index=True)
    return result.sort_values("_hash").head(target)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    gold_ids = set(pd.read_csv(MANUAL_GOLD_PATH, dtype="string")["source_record_id"].astype(str))

    candidates = []
    for year in YEARS:
        path = Path(storage["features_root"]) / "occupation_v0.3" / f"jobs_{year}_occupation_v0.3.parquet"
        frame = pq.read_table(path, columns=[
            "source_record_id", "job_title_raw", "job_title_normalized", "occupation_id",
            "occupation_name", "occupation_method", "occupation_confidence", "occupation_status",
        ]).to_pandas()
        frame["source_record_id"] = frame["source_record_id"].astype(str)
        frame = frame.loc[~frame["source_record_id"].isin(gold_ids)].copy()
        frame["year"] = year
        frame["_hash"] = frame["source_record_id"].map(stable_hash)
        # 每年从每种V3方法中先取固定候选池，避免只抽到高频普通岗位。
        for _, group in frame.groupby("occupation_method", dropna=False):
            candidates.append(group.sort_values("_hash").head(220))

    pool = pd.concat(candidates, ignore_index=True).drop_duplicates("source_record_id")
    context_parts = []
    for year, group in pool.groupby("year", sort=True):
        ids = group["source_record_id"].tolist()
        path = Path(storage["curated_root"]) / "cleaned_v1" / f"jobs_{year}_cleaned.parquet"
        table = ds.dataset(path, format="parquet").to_table(
            columns=["来源记录ID", "初级分类", "职位描述"],
            filter=ds.field("来源记录ID").isin(ids),
        )
        context_parts.append(table.to_pandas().rename(columns={
            "来源记录ID": "source_record_id",
            "初级分类": "primary_category_raw",
            "职位描述": "job_description_raw",
        }))
    context = pd.concat(context_parts, ignore_index=True)
    context["source_record_id"] = context["source_record_id"].astype(str)
    pool = pool.merge(context, on="source_record_id", how="inner", validate="one_to_one")

    classifier = build_classifier()
    predictions = []
    for row in pool.itertuples(index=False):
        result = classifier.classify(
            str(row.job_title_raw), str(row.job_description_raw), str(row.primary_category_raw)
        )
        predictions.append({f"v04_{key}": value for key, value in result.items()})
    pool = pd.concat([pool.reset_index(drop=True), pd.DataFrame(predictions)], axis=1)

    selected = []
    for method, target in TARGETS.items():
        part = pool.loc[pool["v04_occupation_method"].eq(method)].copy()
        selected.append(take_balanced(part, target))
    sample = pd.concat(selected, ignore_index=True)
    if len(sample) != sum(TARGETS.values()) or sample["source_record_id"].duplicated().any():
        counts = sample["v04_occupation_method"].value_counts().to_dict()
        raise RuntimeError(f"独立验证样本数量或主键异常：{counts}")

    sample = sample.sort_values(["v04_occupation_method", "year", "_hash"]).reset_index(drop=True)
    sample.insert(0, "序号", range(1, len(sample) + 1))
    output = pd.DataFrame({
        "序号": sample["序号"],
        "年份": sample["year"],
        "验证分层": sample["v04_occupation_method"],
        "来源记录ID": sample["source_record_id"],
        "原始岗位名称": sample["job_title_raw"],
        "V4标准化岗位名称": sample["v04_job_title_normalized"],
        "V3职业代码": sample["occupation_id"],
        "V3职业名称": sample["occupation_name"],
        "V4职业代码": sample["v04_occupation_id"],
        "V4职业名称": sample["v04_occupation_name"],
        "V4标准职业名称": sample["v04_occupation_standard_name"],
        "V4分类方法": sample["v04_occupation_method"],
        "V4置信度": sample["v04_occupation_confidence"],
        "职位描述节选": sample["job_description_raw"].astype(str).str.slice(0, 1000),
        "人工判断": "",
        "正确职业代码": sample["v04_occupation_id"],
        "错误原因": "",
        "人工备注": "",
        "复核人": "",
        "复核状态": "",
    })
    output.to_csv(SAMPLE_PATH, index=False, encoding="utf-8-sig")

    summary = (
        output.groupby(["验证分层", "年份"], dropna=False)
        .size().rename("条数").reset_index()
    )
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    print(f"OCCUPATION_V04_VALIDATION_SAMPLE={len(output)}")
    print(f"OCCUPATION_V04_VALIDATION_CSV={SAMPLE_PATH}")
    print(output["验证分层"].value_counts().sort_index().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

