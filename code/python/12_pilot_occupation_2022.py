"""按 occupation_rules_v0.1 对2022年岗位做职业分类试运行。

本脚本只生成试运行特征和质检表，不修改 cleaned_v1 或 confirmed_core_v2。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "occupation_pilot_2022_summary.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_pilot_2022_distribution.csv"
RULE_HITS_PATH = QC_ROOT / "occupation_pilot_2022_rule_hits.csv"
UNCLASSIFIED_PATH = QC_ROOT / "occupation_pilot_2022_top_unclassified.csv"
CONFLICTS_PATH = QC_ROOT / "occupation_pilot_2022_top_conflicts.csv"
REVIEW_SAMPLE_PATH = QC_ROOT / "occupation_pilot_2022_review_sample.csv"
EXPECTED_ROWS = 328_548


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or list(rows[0])
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


@lru_cache(maxsize=None)
def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    # “招聘专员”中的“招聘”是人力资源职能，不能当成广告噪声删除。
    text = re.sub(r"^(?:急聘|诚聘|高薪|直招|热招|校招|社招)+[:：_-]*", "", text)
    text = re.sub(r"(?:初级|中级|高级|资深)", "", text)
    text = re.sub(r"(?:招聘)?\d+名?$", "", text)
    text = re.sub(r"\((?:职位编号|岗位编号|编号|急聘|高薪)[^)]*\)$", "", text)
    return text.strip("-—_/|·,，;；:：()[]【】")


def stable_score(record_id: str) -> str:
    return hashlib.sha256(record_id.encode("utf-8")).hexdigest()


def compile_rules(config: dict) -> list[dict]:
    compiled = []
    for order, raw_rule in enumerate(config["rules"]):
        rule = dict(raw_rule)
        rule["order"] = order
        rule["include_re"] = re.compile(rule["include_pattern"], flags=re.IGNORECASE)
        rule["exclude_re"] = (
            re.compile(rule["exclude_pattern"], flags=re.IGNORECASE)
            if rule.get("exclude_pattern") else None
        )
        compiled.append(rule)
    ids = [rule["rule_id"] for rule in compiled]
    if len(ids) != len(set(ids)):
        raise RuntimeError("职业规则编号不唯一")
    return compiled


def build_classifier(config: dict):
    rules = compile_rules(config)
    occupation_names = config["occupation_names"]
    l1_names = config["l1_names"]
    block_values = {normalize_title(value) for value in config["fallback_block_values"]}

    @lru_cache(maxsize=None)
    def classify_once(text: str) -> dict:
        matches = []
        for rule in rules:
            match = rule["include_re"].search(text)
            if match is None:
                continue
            if rule["exclude_re"] is not None and rule["exclude_re"].search(text):
                continue
            matches.append((rule, match.group(0)))
        if not matches:
            return {
                "occupation_id": "Z99", "occupation_l1": "Z",
                "occupation_name": occupation_names["Z99"], "occupation_l1_name": l1_names["Z"],
                "rule_id": "", "match_text": "", "confidence": "unclassified",
                "status": "no_rule_match", "secondary_hits": "", "match_count": 0,
            }
        matches.sort(key=lambda item: (item[0]["priority"], item[0]["order"]))
        best_priority = matches[0][0]["priority"]
        best_occupations = {item[0]["occupation_id"] for item in matches if item[0]["priority"] == best_priority}
        secondary = []
        for rule, matched_text in matches:
            item = f"{rule['occupation_id']}:{rule['rule_id']}:{matched_text}"
            if item not in secondary:
                secondary.append(item)
        if len(best_occupations) > 1:
            return {
                "occupation_id": "Z99", "occupation_l1": "Z",
                "occupation_name": occupation_names["Z99"], "occupation_l1_name": l1_names["Z"],
                "rule_id": "", "match_text": "", "confidence": "unclassified",
                "status": "ambiguous_same_priority", "secondary_hits": " | ".join(secondary),
                "match_count": len({item[0]["occupation_id"] for item in matches}),
            }
        chosen_rule, chosen_text = matches[0]
        occupation_id = chosen_rule["occupation_id"]
        return {
            "occupation_id": occupation_id, "occupation_l1": occupation_id[0],
            "occupation_name": occupation_names[occupation_id],
            "occupation_l1_name": l1_names[occupation_id[0]],
            "rule_id": chosen_rule["rule_id"], "match_text": chosen_text,
            "confidence": chosen_rule["confidence"], "status": "classified",
            "secondary_hits": " | ".join(secondary[1:]),
            "match_count": len({item[0]["occupation_id"] for item in matches}),
        }

    def classify(title: object, primary_category: object) -> dict:
        title_text = normalize_title(str(title)) if title is not None and not pd.isna(title) else ""
        primary = classify_once(title_text) if title_text else classify_once("")
        primary["normalized_title"] = title_text
        primary["source"] = "job_title"
        if primary["occupation_id"] != "Z99" or primary["status"] == "ambiguous_same_priority":
            return primary

        fallback_text = (
            normalize_title(str(primary_category))
            if primary_category is not None and not pd.isna(primary_category) else ""
        )
        if not fallback_text or fallback_text in block_values:
            return primary
        fallback = dict(classify_once(fallback_text))
        if fallback["occupation_id"] == "Z99":
            return primary
        fallback["normalized_title"] = title_text
        fallback["source"] = "primary_category_fallback"
        fallback["confidence"] = "low"
        fallback["status"] = "classified_by_fallback"
        fallback["match_text"] = f"初级分类:{fallback['match_text']}"
        return fallback

    return classify, rules


def make_review_sample(frame: pd.DataFrame, target: int = 800) -> pd.DataFrame:
    selected: list[str] = []
    for _, group in frame.groupby("occupation_id", sort=True):
        ordered = group.assign(_score=group["source_record_id"].map(stable_score)).sort_values("_score")
        selected.extend(ordered.head(12)["source_record_id"].tolist())
    for condition in [
        frame["occupation_id"].eq("Z99"),
        frame["occupation_match_count"].gt(1),
        frame["occupation_confidence"].eq("low"),
    ]:
        candidates = frame.loc[condition & ~frame["source_record_id"].isin(selected)].copy()
        candidates["_score"] = candidates["source_record_id"].map(stable_score)
        selected.extend(candidates.sort_values("_score").head(120)["source_record_id"].tolist())
    remaining = frame.loc[~frame["source_record_id"].isin(selected)].copy()
    remaining["_score"] = remaining["source_record_id"].map(stable_score)
    selected.extend(remaining.sort_values("_score").head(max(0, target - len(selected)))["source_record_id"].tolist())
    sample = frame.set_index("source_record_id").loc[selected[:target]].reset_index()
    sample["manual_correct"] = ""
    sample["manual_occupation_id"] = ""
    sample["manual_error_reason"] = ""
    sample["manual_notes"] = ""
    return sample


def main() -> int:
    storage = load_json(STORAGE_PATH)
    config = load_json(RULE_PATH)
    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    output_root = Path(storage["features_root"]) / "occupation_pilot_v0.1"
    output_path = output_root / "jobs_2022_occupation_pilot.parquet"
    output_root.mkdir(parents=True, exist_ok=True)

    source = pq.read_table(
        cleaned_path,
        columns=["来源记录ID", "招聘岗位", "初级分类", "招聘类别"],
    ).to_pandas()
    source = source.rename(columns={
        "来源记录ID": "source_record_id", "招聘岗位": "job_title_raw",
        "初级分类": "primary_category_raw", "招聘类别": "recruitment_category_raw",
    })
    if len(source) != EXPECTED_ROWS or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗输入行数或来源记录ID异常")
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    if set(source["source_record_id"]) != core_ids:
        raise RuntimeError("2022年清洗数据与confirmed_core_v2来源记录ID不一致")

    classify, rules = build_classifier(config)
    cache: dict[tuple[str, str], dict] = {}
    results = []
    for title, primary_category in zip(source["job_title_raw"], source["primary_category_raw"]):
        key = (str(title), str(primary_category))
        if key not in cache:
            cache[key] = classify(title, primary_category)
        results.append(cache[key])
    result_frame = pd.DataFrame(results)
    output = pd.DataFrame({
        "source_record_id": source["source_record_id"].astype("string"),
        "occupation_l1": result_frame["occupation_l1"].astype("string"),
        "occupation_l1_name": result_frame["occupation_l1_name"].astype("string"),
        "occupation_id": result_frame["occupation_id"].astype("string"),
        "occupation_name": result_frame["occupation_name"].astype("string"),
        "job_title_raw": source["job_title_raw"].astype("string"),
        "job_title_normalized": result_frame["normalized_title"].astype("string"),
        "occupation_rule_id": result_frame["rule_id"].astype("string"),
        "occupation_match_text": result_frame["match_text"].astype("string"),
        "occupation_source": result_frame["source"].astype("string"),
        "occupation_confidence": result_frame["confidence"].astype("string"),
        "occupation_status": result_frame["status"].astype("string"),
        "occupation_match_count": result_frame["match_count"].astype("int16"),
        "occupation_secondary_hits": result_frame["secondary_hits"].astype("string"),
    })
    temp_path = output_path.with_suffix(".parquet.tmp")
    if temp_path.exists():
        temp_path.unlink()
    pq.write_table(pa.Table.from_pandas(output, preserve_index=False), temp_path, compression="zstd")
    os.replace(temp_path, output_path)

    total = len(output)
    summary_rows = []
    for dimension, series in [
        ("occupation_status", output["occupation_status"]),
        ("occupation_confidence", output["occupation_confidence"]),
        ("occupation_source", output["occupation_source"]),
        ("occupation_l1", output["occupation_l1"]),
    ]:
        for value, count in series.value_counts(dropna=False).items():
            summary_rows.append({
                "dimension": dimension, "value": value, "count": int(count),
                "share": round(int(count) / total, 8),
            })
    write_csv(SUMMARY_PATH, summary_rows)

    distribution = []
    for occupation_id, group in output.groupby("occupation_id", sort=True):
        confidence_counts = group["occupation_confidence"].value_counts()
        distribution.append({
            "occupation_l1": group["occupation_l1"].iloc[0],
            "occupation_l1_name": group["occupation_l1_name"].iloc[0],
            "occupation_id": occupation_id,
            "occupation_name": group["occupation_name"].iloc[0],
            "count": len(group), "share": round(len(group) / total, 8),
            "high": int(confidence_counts.get("high", 0)),
            "medium": int(confidence_counts.get("medium", 0)),
            "low": int(confidence_counts.get("low", 0)),
            "unclassified": int(confidence_counts.get("unclassified", 0)),
        })
    write_csv(DISTRIBUTION_PATH, distribution)

    rule_lookup = {rule["rule_id"]: rule for rule in rules}
    rule_counts = output.loc[output["occupation_rule_id"] != "", "occupation_rule_id"].value_counts()
    rule_rows = []
    for rule_id, count in rule_counts.items():
        rule = rule_lookup[rule_id]
        rule_rows.append({
            "rule_id": rule_id, "occupation_id": rule["occupation_id"],
            "occupation_name": config["occupation_names"][rule["occupation_id"]],
            "priority": rule["priority"], "rule_confidence": rule["confidence"],
            "count": int(count), "include_pattern": rule["include_pattern"],
            "exclude_pattern": rule.get("exclude_pattern", ""),
        })
    write_csv(RULE_HITS_PATH, rule_rows)

    z99 = output.loc[output["occupation_id"] == "Z99"]
    unclassified_rows = []
    for (normalized, raw, status), count in (
        z99.groupby(["job_title_normalized", "job_title_raw", "occupation_status"], dropna=False)
        .size().sort_values(ascending=False).head(300).items()
    ):
        unclassified_rows.append({
            "job_title_normalized": normalized, "job_title_example": raw,
            "occupation_status": status, "count": int(count),
        })
    write_csv(UNCLASSIFIED_PATH, unclassified_rows)

    conflict_frame = output.loc[output["occupation_match_count"] > 1]
    conflict_rows = []
    for (normalized, occupation_id, secondary), count in (
        conflict_frame.groupby(
            ["job_title_normalized", "occupation_id", "occupation_secondary_hits"], dropna=False
        ).size().sort_values(ascending=False).head(300).items()
    ):
        conflict_rows.append({
            "job_title_normalized": normalized, "chosen_occupation_id": occupation_id,
            "secondary_hits": secondary, "count": int(count),
        })
    if not conflict_rows:
        conflict_rows = [{"job_title_normalized": "", "chosen_occupation_id": "", "secondary_hits": "", "count": 0}]
    write_csv(CONFLICTS_PATH, conflict_rows)

    review = make_review_sample(output)
    review.to_csv(REVIEW_SAMPLE_PATH, index=False, encoding="utf-8-sig")

    classified = int((output["occupation_id"] != "Z99").sum())
    ambiguous = int((output["occupation_status"] == "ambiguous_same_priority").sum())
    fallback = int((output["occupation_source"] == "primary_category_fallback").sum())
    manifest = {
        "version": config["version"], "year": 2022, "input_rows": total,
        "classified_rows": classified, "classified_share": classified / total,
        "z99_rows": total - classified, "ambiguous_rows": ambiguous,
        "fallback_rows": fallback, "output_file": str(output_path),
        "rule_file": str(RULE_PATH), "review_sample_file": str(REVIEW_SAMPLE_PATH),
    }
    (output_root / "manifest_2022.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OCCUPATION_PILOT_ROWS={total}")
    print(f"OCCUPATION_CLASSIFIED={classified} ({classified / total:.2%})")
    print(f"OCCUPATION_Z99={total - classified} ({1 - classified / total:.2%})")
    print(f"OCCUPATION_AMBIGUOUS={ambiguous}")
    print(f"OCCUPATION_FALLBACK={fallback}")
    print(f"OCCUPATION_PILOT_OUTPUT={output_path}")
    print("OCCUPATION_PILOT_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
