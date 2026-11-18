"""在2022年试运行 V4.2 证据补充规则，并生成透明的复核样本。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz import fuzz, process

from occupation_v042_evidence import OccupationEvidenceClassifier
from occupation_v04 import build_classifier


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118"
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
CANDIDATE_VERSION = "occupation_v0.4.2_candidate_2022_pilot_20261118"


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def fuzzy_diagnostic(classifier, title: str) -> tuple[str, float, float, str]:
    """返回80分以上模糊匹配的最佳37类候选，但不单独据此分类。"""
    choices = [item["candidate"] for item in classifier.fuzzy_candidates]
    matches = process.extract(title, choices, scorer=fuzz.ratio, limit=len(choices))
    best_by_group: dict[str, tuple[float, dict]] = {}
    for _, score, index in matches:
        item = classifier.fuzzy_candidates[index]
        previous = best_by_group.get(item["occupation_id"])
        if previous is None or score > previous[0]:
            best_by_group[item["occupation_id"]] = (float(score), item)
    ranked = sorted(best_by_group.values(), key=lambda pair: (-pair[0], pair[1]["occupation_id"]))
    if not ranked or ranked[0][0] < 80:
        return "", 0.0, 0.0, ""
    top1, item = ranked[0]
    top2 = ranked[1][0] if len(ranked) > 1 else 0.0
    return item["occupation_id"], top1, top1 - top2, item["standard_name"]


def select_review_sample(evidence: pd.DataFrame, seed: int = 20261118) -> pd.DataFrame:
    """按证据来源分层抽400条；不足的层由其他层补足。"""
    accepted = evidence.loc[evidence["accepted"]].copy()
    remaining = evidence.loc[~evidence["accepted"]].copy()
    targets = {
        "decisive_title_and_description": 60,
        "decisive_title_rule": 20,
        "title_and_description_evidence": 80,
        "description_multi_evidence": 120,
        "fuzzy_name_and_description_evidence": 80,
    }
    pieces: list[pd.DataFrame] = []
    selected_ids: set[str] = set()
    for method, target in targets.items():
        pool = accepted.loc[accepted["method"].eq(method)]
        take = min(target, len(pool))
        if take:
            part = pool.sample(n=take, random_state=seed + len(pieces))
            pieces.append(part)
            selected_ids.update(part["source_record_id"].astype(str))

    # 保留40条仍为Z99的边界案例，帮助判断规则还缺什么。
    if len(remaining):
        unresolved = remaining.sort_values(
            ["score_top1", "score_margin"], ascending=[False, True]
        ).head(40)
        pieces.append(unresolved)
        selected_ids.update(unresolved["source_record_id"].astype(str))

    sample = pd.concat(pieces, ignore_index=True) if pieces else evidence.head(0).copy()
    if len(sample) < 400:
        pool = accepted.loc[~accepted["source_record_id"].astype(str).isin(selected_ids)]
        take = min(400 - len(sample), len(pool))
        if take:
            sample = pd.concat(
                [sample, pool.sample(n=take, random_state=seed + 99)], ignore_index=True
            )
    sample = sample.head(400).copy()
    sample.insert(0, "复核序号", range(1, len(sample) + 1))
    sample["人工判断"] = ""
    sample["人工正确职业代码"] = ""
    sample["人工备注"] = ""
    return sample


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    QC_DIR.mkdir(parents=True, exist_ok=True)
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    base_rules = json.loads(BASE_RULE_PATH.read_text(encoding="utf-8"))
    occupation_names = base_rules["occupation_names"]
    l1_names = base_rules["l1_names"]

    v41_path = Path(storage["features_root"]) / "occupation_v0.4.1" / "jobs_2022_occupation_v0.4.1.parquet"
    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    candidate_root = Path(storage["features_root"]) / "occupation_v0.4.2_candidate"
    candidate_root.mkdir(parents=True, exist_ok=True)
    output_path = candidate_root / "jobs_2022_occupation_v0.4.2_candidate.parquet"

    source = pq.read_table(v41_path).to_pandas()
    source["source_record_id"] = source["source_record_id"].astype(str)
    cleaned = pq.read_table(
        cleaned_path, columns=["来源记录ID", "初级分类", "职位描述"]
    ).to_pandas().rename(columns={
        "来源记录ID": "source_record_id",
        "初级分类": "primary_category",
        "职位描述": "job_description",
    })
    cleaned["source_record_id"] = cleaned["source_record_id"].astype(str)
    if cleaned["source_record_id"].duplicated().any():
        raise RuntimeError("2022清洗表主键重复")
    joined = source.merge(cleaned, on="source_record_id", how="left", validate="one_to_one")

    z99_mask = joined["occupation_id"].eq("Z99")
    z99 = joined.loc[z99_mask, [
        "source_record_id", "job_title_raw", "job_title_normalized",
        "primary_category", "job_description", "occupation_status", "occupation_score_top1",
    ]].copy()
    classifier = OccupationEvidenceClassifier()
    v41_classifier = build_classifier()
    fuzzy_titles = z99.loc[z99["occupation_score_top1"].ge(80), "job_title_normalized"].drop_duplicates()
    fuzzy_lookup = {
        title: fuzzy_diagnostic(v41_classifier, title)
        for title in fuzzy_titles
    }
    fuzzy_inputs = [
        fuzzy_lookup.get(title, ("", 0.0, 0.0, ""))
        for title in z99["job_title_normalized"]
    ]
    evidence_results = [
        classifier.classify(title, description, primary, fuzzy_id, fuzzy_score, fuzzy_margin)
        for title, description, primary, (fuzzy_id, fuzzy_score, fuzzy_margin, _) in zip(
            z99["job_title_normalized"], z99["job_description"], z99["primary_category"], fuzzy_inputs
        )
    ]
    evidence = pd.concat(
        [z99.reset_index(drop=True), pd.DataFrame(evidence_results)], axis=1
    )
    accepted = evidence.loc[evidence["accepted"]].copy()
    accepted_lookup = accepted.set_index("source_record_id")

    result = source.copy()
    accepted_mask = result["source_record_id"].isin(accepted_lookup.index)
    ids = result.loc[accepted_mask, "source_record_id"]
    codes = ids.map(accepted_lookup["candidate_occupation_id"])
    result.loc[accepted_mask, "occupation_id"] = codes.to_numpy()
    result.loc[accepted_mask, "occupation_name"] = codes.map(occupation_names).to_numpy()
    result.loc[accepted_mask, "occupation_standard_name"] = ids.map(
        accepted_lookup["candidate_standard_name"]
    ).to_numpy()
    result.loc[accepted_mask, "occupation_l1"] = codes.str[0].to_numpy()
    result.loc[accepted_mask, "occupation_l1_name"] = codes.str[0].map(l1_names).to_numpy()
    result.loc[accepted_mask, "occupation_method"] = ids.map(accepted_lookup["method"]).to_numpy()
    result.loc[accepted_mask, "occupation_rule_id"] = "V042_EVIDENCE_SUPPLEMENT"
    result.loc[accepted_mask, "occupation_confidence"] = ids.map(
        accepted_lookup["confidence"]
    ).to_numpy()
    result.loc[accepted_mask, "occupation_status"] = "v042_evidence_accepted"
    result.loc[accepted_mask, "occupation_review_flag"] = 1
    result.loc[accepted_mask, "occupation_score_top1"] = ids.map(
        accepted_lookup["score_top1"]
    ).astype(float).to_numpy()
    result.loc[accepted_mask, "occupation_score_top2"] = ids.map(
        accepted_lookup["score_top2"]
    ).astype(float).to_numpy()
    result.loc[accepted_mask, "occupation_score_margin"] = ids.map(
        accepted_lookup["score_margin"]
    ).astype(float).to_numpy()
    result["occupation_version"] = CANDIDATE_VERSION

    # 保持正式职业特征表的字段和V4.1完全一致，详细证据另存QC文件。
    result["occupation_review_flag"] = result["occupation_review_flag"].astype("int8")
    for column in ["occupation_score_top1", "occupation_score_top2", "occupation_score_margin"]:
        result[column] = result[column].astype("float32")
    temp_path = output_path.with_suffix(".parquet.tmp")
    temp_path.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pandas(result, preserve_index=False), temp_path, compression="zstd")
    os.replace(temp_path, output_path)

    evidence_export = evidence.copy()
    evidence_export["job_description_excerpt"] = evidence_export["job_description"].fillna("").astype(str).str.slice(0, 600)
    evidence_export = evidence_export.drop(columns=["job_description"])
    evidence_root = Path(storage["evidence_root"]) / "occupation_v0.4.2_candidate"
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / "occupation_v042_2022_z99_evidence_audit.parquet"
    pq.write_table(
        pa.Table.from_pandas(evidence_export, preserve_index=False),
        evidence_path,
        compression="zstd",
    )
    review = select_review_sample(evidence_export)
    review_path = OUTPUT_DIR / "occupation_v042_2022_manual_review_sample_400.csv"
    write_csv(review_path, review)

    old_classified = int(source["occupation_id"].ne("Z99").sum())
    new_classified = int(result["occupation_id"].ne("Z99").sum())
    total = len(result)
    summary = pd.DataFrame([{
        "year": 2022,
        "records": total,
        "v041_classified": old_classified,
        "v041_coverage": old_classified / total,
        "v042_newly_classified_from_z99": len(accepted),
        "v042_candidate_classified": new_classified,
        "v042_candidate_coverage": new_classified / total,
        "remaining_z99": total - new_classified,
        "review_sample_rows": len(review),
        "candidate_output": str(output_path),
    }])
    write_csv(QC_DIR / "occupation_v042_2022_summary.csv", summary)

    method_summary = (
        evidence.groupby(["accepted", "method", "status"], dropna=False)
        .size().rename("count").reset_index()
        .sort_values("count", ascending=False)
    )
    method_summary["share_of_v041_z99"] = method_summary["count"] / len(evidence)
    write_csv(QC_DIR / "occupation_v042_2022_evidence_methods.csv", method_summary)

    distribution = (
        result.groupby(["occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name"], dropna=False)
        .size().rename("count").reset_index().sort_values("count", ascending=False)
    )
    distribution["share"] = distribution["count"] / total
    write_csv(QC_DIR / "occupation_v042_2022_distribution.csv", distribution)

    report_path = QC_DIR / "occupation_v042_2022_report.md"
    report_path.write_text(f"""# occupation V4.2 2022年候选试运行报告

## 核心结果

- 2022年总记录：{total:,}条；
- V4.1已分类：{old_classified:,}条，覆盖率{old_classified / total:.2%}；
- V4.2本轮仅从Z99新增：{len(accepted):,}条；
- V4.2候选版已分类：{new_classified:,}条，覆盖率{new_classified / total:.2%}；
- 仍为Z99：{total - new_classified:,}条；
- 新增分类全部标记为需要人工抽样复核，尚未作为正式回归数据。

## 安全边界

1. V4.1中已分类的记录一条也不改；
2. “初级分类”最多加1分，只能确认，不能单独决定；
3. 接受条件为总分至少5分、领先第二名至少2分，并且有标题强证据或至少两项独立的职位描述强证据；
4. 400条分层样本复核准确率达到90%后，才能讨论全量运行。

## 文件

- 候选特征表：`{output_path}`
- 全部Z99证据审计：`{evidence_path}`
- 400条人工复核样本：`{review_path}`
""", encoding="utf-8")

    print(f"ROWS={total}")
    print(f"V041_COVERAGE={old_classified / total:.6f}")
    print(f"NEWLY_CLASSIFIED={len(accepted)}")
    print(f"V042_CANDIDATE_COVERAGE={new_classified / total:.6f}")
    print(f"REVIEW_SAMPLE={len(review)}")
    print(f"OUTPUT={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
