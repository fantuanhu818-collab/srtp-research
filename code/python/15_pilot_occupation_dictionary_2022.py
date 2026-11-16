"""使用职业大典正式版、别名和RapidFuzz重新试跑2022年职业变量。

正式 occupation_id 使用职业大典小类代码。没有可靠匹配的记录使用官方
不便分类代码8-00-00，并保留分数、分差、匹配方法和人工复核标记。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz import fuzz, process


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
DICTIONARY_PATH = PROJECT_ROOT / "config" / "occupation_dictionary_2022_official.csv"
ALIAS_PATH = PROJECT_ROOT / "config" / "occupation_aliases_v0.2.csv"
LEGACY_FALLBACK_PATH = PROJECT_ROOT / "config" / "occupation_legacy_group_to_small_v0.2.csv"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
EXPECTED_ROWS = 328_548
UNCLASSIFIED_SMALL_CODE = "8-00-00"
UNCLASSIFIED_FINE_CODE = "8-00-00-00"
MATCHER_VERSION = "occupation_v0.2_levenshtein_ratio_20261116"
MATCH_SCORER_NAME = "rapidfuzz.fuzz.ratio"

SUMMARY_PATH = QC_ROOT / "occupation_v02_2022_summary.csv"
THRESHOLD_PATH = QC_ROOT / "occupation_v02_2022_threshold_comparison.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_v02_2022_distribution.csv"
UNCLASSIFIED_PATH = QC_ROOT / "occupation_v02_2022_top_unclassified.csv"
CONFLICT_PATH = QC_ROOT / "occupation_v02_2022_top_conflicts.csv"
REVIEW_PATH = QC_ROOT / "occupation_v02_2022_review_sample.csv"
REPORT_PATH = QC_ROOT / "occupation_v02_2022_report.md"

GENERIC_BLOCK_TITLES = {
    "工程师", "技术员", "技术工程师", "管理员", "专员", "助理", "经理", "主管", "总监", "文员",
    "项目经理", "项目工程师", "项目专员", "项目助理", "产品经理", "研发工程师", "工艺工程师",
    "生产主管", "生产经理", "生产技术员", "操作工", "普工", "管培生", "储备干部", "业务经理",
    "设备管理员", "区域经理", "综合管理员",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def normalize_match_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"^(?:急聘|诚聘|高薪|直招|热招|校招|社招)+[:：_\-]*", "", text)
    text = re.sub(r"(?:初级|中级|高级|资深)", "", text)
    text = re.sub(r"(?:招聘)?\d+名?$", "", text)
    text = re.sub(r"\((?:职位编号|岗位编号|编号|急聘|高薪)[^)]*\)$", "", text)
    text = text.replace("人资", "人力资源").replace("品质", "质量").replace("安卓", "android")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[·•,，;；:：/_|\\\-—]+", "", text)
    return text.strip("()[]【】")


def load_v01_classifier():
    module_path = PROJECT_ROOT / "code" / "python" / "12_pilot_occupation_2022.py"
    spec = importlib.util.spec_from_file_location("occupation_v01_pilot", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入v0.1职业分类器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    classifier, _ = module.build_classifier(load_json(RULE_PATH))
    return classifier


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def choose_review_sample(frame: pd.DataFrame, target: int = 800) -> pd.DataFrame:
    groups = [
        ("exact_manual", frame["occupation_match_method"].eq("exact_manual"), 80),
        ("exact_standard", frame["occupation_match_method"].isin(["exact_official", "exact_systematic"]), 60),
        ("fuzzy_accepted", frame["occupation_status"].eq("fuzzy_high_accepted"), 120),
        ("legacy_group_fallback", frame["occupation_status"].eq("legacy_group_fallback"), 220),
        ("score_80_89", frame["occupation_score_top1"].between(80, 89.999, inclusive="both"), 100),
        ("conflict_or_generic", frame["occupation_status"].isin(["fuzzy_rule_conflict", "generic_title_blocked"]), 100),
        ("unclassified", frame["occupation_id"].eq(UNCLASSIFIED_SMALL_CODE), 120),
    ]
    picked: list[pd.DataFrame] = []
    used: set[str] = set()
    for stratum, condition, count in groups:
        candidates = frame.loc[condition & ~frame["source_record_id"].isin(used)].copy()
        candidates["_sample_hash"] = candidates["source_record_id"].map(stable_hash)
        part = candidates.sort_values("_sample_hash").head(count).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", stratum)
        picked.append(part)
        used.update(part["source_record_id"].tolist())
    sample = pd.concat(picked, ignore_index=True) if picked else frame.head(0).copy()
    if len(sample) < target:
        remaining = frame.loc[~frame["source_record_id"].isin(used)].copy()
        remaining["_sample_hash"] = remaining["source_record_id"].map(stable_hash)
        part = remaining.sort_values("_sample_hash").head(target - len(sample)).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", "fill")
        sample = pd.concat([sample, part], ignore_index=True)
    keep = [
        "review_stratum", "source_record_id", "job_title_raw", "job_title_normalized", "occupation_id",
        "occupation_small_name", "occupation_fine_code", "occupation_fine_name", "occupation_match_method",
        "occupation_match_target", "occupation_score_top1", "occupation_score_top2", "occupation_score_margin",
        "occupation_confidence", "occupation_status", "occupation_review_flag", "legacy_occupation_id",
        "legacy_occupation_name", "occupation_rule_consistency",
    ]
    sample = sample[keep].copy()
    sample["manual_small_correct"] = ""
    sample["manual_fine_correct"] = ""
    sample["manual_correct_small_code"] = ""
    sample["manual_correct_fine_code"] = ""
    sample["manual_error_reason"] = ""
    sample["manual_notes"] = ""
    return sample


def main() -> int:
    storage = load_json(STORAGE_PATH)
    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    output_root = Path(storage["features_root"]) / "occupation_pilot_v0.2"
    output_path = output_root / "jobs_2022_occupation_v0.2.parquet"
    unique_path = output_root / "unique_title_matches_2022.parquet"
    manifest_path = output_root / "manifest_2022.json"
    output_root.mkdir(parents=True, exist_ok=True)

    dictionary = pd.read_csv(DICTIONARY_PATH, dtype="string").fillna("")
    aliases = pd.read_csv(ALIAS_PATH, dtype="string").fillna("")
    aliases = aliases.loc[aliases["usable_for_matching"].eq("1")].copy()
    if len(dictionary) != 1_639 or aliases.empty:
        raise RuntimeError("职业大典代码表或别名表未准备好")
    dictionary_by_fine = dictionary.set_index("occupation_fine_code").to_dict("index")
    dictionary_by_small = dictionary.drop_duplicates("occupation_small_code").set_index("occupation_small_code").to_dict("index")
    legacy_fallback = pd.read_csv(LEGACY_FALLBACK_PATH, dtype="string").fillna("")
    if legacy_fallback["legacy_occupation_id"].duplicated().any():
        raise RuntimeError("旧职业组到职业小类兜底表存在重复编号")
    legacy_fallback_map = legacy_fallback.set_index("legacy_occupation_id").to_dict("index")
    for legacy_id, fallback in legacy_fallback_map.items():
        code = fallback["occupation_small_code"]
        if code not in dictionary_by_small or dictionary_by_small[code]["occupation_small_name"] != fallback["occupation_small_name"]:
            raise RuntimeError(f"旧职业组兜底代码或名称错误：{legacy_id} -> {code}")
    unclassified = dictionary_by_fine[UNCLASSIFIED_FINE_CODE]

    source = pq.read_table(cleaned_path, columns=["来源记录ID", "招聘岗位", "初级分类"]).to_pandas()
    source = source.rename(columns={"来源记录ID": "source_record_id", "招聘岗位": "job_title_raw", "初级分类": "primary_category_raw"})
    if len(source) != EXPECTED_ROWS or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年输入行数或来源记录ID异常")
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    if set(source["source_record_id"]) != core_ids:
        raise RuntimeError("2022年清洗数据与confirmed_core_v2来源记录ID不一致")
    source["job_title_normalized"] = source["job_title_raw"].map(normalize_match_text).astype("string")

    alias_records = aliases.to_dict("records")
    choices = [record["alias_normalized"] for record in alias_records]
    exact_lookup = {record["alias_normalized"]: record for record in alias_records}
    generic_normalized = {normalize_match_text(value) for value in GENERIC_BLOCK_TITLES}
    legacy_classifier = load_v01_classifier()

    target_legacy_cache: dict[str, str] = {}
    def target_legacy(record: dict) -> str:
        key = record["occupation_small_code"]
        if key not in target_legacy_cache:
            text = record["occupation_fine_name"] or record["occupation_small_name"]
            target_legacy_cache[key] = legacy_classifier(text, "")["occupation_id"]
        return target_legacy_cache[key]

    unique_counts = source["job_title_normalized"].value_counts(dropna=False)
    unique_titles = [str(value) for value in unique_counts.index]
    title_results: dict[str, dict] = {}
    alias_candidate_lookup = {
        (normalize_match_text(record["alias"]), record["occupation_small_code"]): record
        for record in alias_records
    }
    cache_valid = False
    if unique_path.exists() and manifest_path.exists():
        previous_manifest = load_json(manifest_path)
        cache_valid = (
            previous_manifest.get("dictionary_sha256") == sha256(DICTIONARY_PATH)
            and previous_manifest.get("alias_sha256") == sha256(ALIAS_PATH)
            and previous_manifest.get("matcher_version") == MATCHER_VERSION
        )
    if cache_valid:
        cached = pq.read_table(unique_path).to_pandas()
        if set(cached["job_title_normalized"].astype(str)) == set(unique_titles):
            for row in cached.itertuples(index=False):
                candidate_code = str(row.candidate_small_code) if not pd.isna(row.candidate_small_code) else ""
                target = str(row.occupation_match_target) if not pd.isna(row.occupation_match_target) else ""
                candidate = alias_candidate_lookup.get((normalize_match_text(target), candidate_code)) if candidate_code else None
                title_results[str(row.job_title_normalized)] = {
                    "match_method": str(row.occupation_match_method),
                    "match_target": target,
                    "target_level": str(row.occupation_target_level) if not pd.isna(row.occupation_target_level) else "",
                    "top1": float(row.occupation_score_top1),
                    "top2": float(row.occupation_score_top2),
                    "margin": float(row.occupation_score_margin),
                    "confidence": (
                        "high" if str(row.pre_rule_status) in {"exact_accepted", "fuzzy_high_candidate"}
                        else "medium" if str(row.pre_rule_status) == "score_80_89_review"
                        else "low" if str(row.pre_rule_status) == "score_70_79_diagnostic"
                        else "unclassified"
                    ),
                    "status": str(row.pre_rule_status),
                    "review_flag": int(str(row.pre_rule_status) not in {"exact_accepted", "fuzzy_high_candidate"}),
                    "candidate": candidate,
                }
            missing_cached_candidates = sum(
                int(result["candidate"] is None and bool(result["match_target"]))
                for result in title_results.values()
            )
            if missing_cached_candidates:
                raise RuntimeError(f"模糊匹配缓存有{missing_cached_candidates}个候选无法还原")
            print(f"FUZZY_CACHE_USED={len(title_results)}", flush=True)
        else:
            title_results.clear()
            cache_valid = False

    for position, title in enumerate(unique_titles, start=1) if not cache_valid else []:
        if not title:
            title_results[title] = {
                "match_method": "unclassified", "match_target": "", "target_level": "",
                "top1": 0.0, "top2": 0.0, "margin": 0.0, "confidence": "unclassified",
                "status": "empty_title", "review_flag": 1, "candidate": None,
            }
            continue
        exact = exact_lookup.get(title)
        if exact is not None:
            method_map = {
                "manual_v0.2": "exact_manual",
                "official_name": "exact_official",
                "systematic_variant": "exact_systematic",
            }
            title_results[title] = {
                "match_method": method_map.get(exact["alias_source"], "exact_alias"),
                "match_target": exact["alias"], "target_level": exact["target_level"],
                "top1": 100.0, "top2": 0.0, "margin": 100.0, "confidence": "high",
                "status": "exact_accepted", "review_flag": 0, "candidate": exact,
            }
            continue
        if title in generic_normalized:
            title_results[title] = {
                "match_method": "unclassified", "match_target": "", "target_level": "",
                "top1": 0.0, "top2": 0.0, "margin": 0.0, "confidence": "unclassified",
                "status": "generic_title_blocked", "review_flag": 1, "candidate": None,
            }
            continue

        raw_matches = process.extract(title, choices, scorer=fuzz.ratio, limit=30, score_cutoff=0)
        best_by_small: dict[str, tuple[float, dict]] = {}
        for _, score, index in raw_matches:
            record = alias_records[index]
            code = record["occupation_small_code"]
            previous = best_by_small.get(code)
            if previous is None or score > previous[0]:
                best_by_small[code] = (float(score), record)
        ranked = sorted(best_by_small.values(), key=lambda item: (-item[0], int(item[1]["target_level"] != "fine"), item[1]["alias_normalized"]))
        top1, candidate = ranked[0]
        top2 = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = top1 - top2
        if candidate["occupation_small_code"] == UNCLASSIFIED_SMALL_CODE:
            status, confidence, review = "unclassified_target", "unclassified", 1
        elif top1 >= 90 and margin >= 5:
            status, confidence, review = "fuzzy_high_candidate", "high", 0
        elif top1 >= 80:
            status, confidence, review = "score_80_89_review", "medium", 1
        elif top1 >= 70:
            status, confidence, review = "score_70_79_diagnostic", "low", 1
        else:
            status, confidence, review = "score_below_70", "unclassified", 1
        title_results[title] = {
            "match_method": "fuzzy_alias", "match_target": candidate["alias"],
            "target_level": candidate["target_level"], "top1": top1, "top2": top2,
            "margin": margin, "confidence": confidence, "status": status,
            "review_flag": review, "candidate": candidate,
        }
        if position % 10_000 == 0:
            print(f"FUZZY_PROGRESS={position}/{len(unique_titles)}", flush=True)

    output_rows: list[dict] = []
    for row in source.itertuples(index=False):
        match = title_results[str(row.job_title_normalized)]
        legacy = legacy_classifier(row.job_title_raw, row.primary_category_raw)
        candidate = match["candidate"]
        rule_consistency = "not_comparable"
        accepted = match["status"] in {"exact_accepted", "fuzzy_high_candidate"}
        high_confidence_accepted = accepted
        status = match["status"]
        confidence = match["confidence"]
        review_flag = match["review_flag"]
        if candidate is not None:
            candidate_legacy = target_legacy(candidate)
            if legacy["occupation_id"] != "Z99" and candidate_legacy != "Z99":
                rule_consistency = "same" if legacy["occupation_id"] == candidate_legacy else "conflict"
            if status == "fuzzy_high_candidate" and rule_consistency == "conflict":
                accepted = False
                high_confidence_accepted = False
                status = "fuzzy_rule_conflict"
                confidence = "medium"
                review_flag = 1
            elif status == "fuzzy_high_candidate":
                status = "fuzzy_high_accepted"

        fallback = None
        if not accepted and legacy["status"] == "classified" and legacy["source"] == "job_title":
            fallback = legacy_fallback_map.get(legacy["occupation_id"])
            if fallback is not None:
                accepted = True
                status = "legacy_group_fallback"
                confidence = "medium"
                review_flag = 1

        if accepted and fallback is not None:
            small_code = fallback["occupation_small_code"]
            detail = dictionary_by_small[small_code]
            small_name = detail["occupation_small_name"]
            fine_code, fine_name = "", ""
            middle_code, middle_name = detail["occupation_middle_code"], detail["occupation_middle_name"]
            major_code, major_name = detail["occupation_major_code"], detail["occupation_major_name"]
            green, digital = "", ""
            match_method = "legacy_group_fallback"
            match_target = small_name
            target_level = "small"
        elif accepted and candidate is not None:
            small_code = candidate["occupation_small_code"]
            small_name = candidate["occupation_small_name"]
            fine_code = candidate["occupation_fine_code"]
            fine_name = candidate["occupation_fine_name"]
            if fine_code:
                detail = dictionary_by_fine[fine_code]
                middle_code, middle_name = detail["occupation_middle_code"], detail["occupation_middle_name"]
                major_code, major_name = detail["occupation_major_code"], detail["occupation_major_name"]
                green, digital = detail["is_green_occupation"], detail["is_digital_occupation"]
            else:
                detail = dictionary.loc[dictionary["occupation_small_code"].eq(small_code)].iloc[0]
                middle_code, middle_name = detail["occupation_middle_code"], detail["occupation_middle_name"]
                major_code, major_name = detail["occupation_major_code"], detail["occupation_major_name"]
                green, digital = "", ""
            match_method = match["match_method"]
            match_target = match["match_target"]
            target_level = match["target_level"]
        else:
            small_code, small_name = UNCLASSIFIED_SMALL_CODE, unclassified["occupation_small_name"]
            fine_code, fine_name = UNCLASSIFIED_FINE_CODE, unclassified["occupation_fine_name"]
            middle_code, middle_name = unclassified["occupation_middle_code"], unclassified["occupation_middle_name"]
            major_code, major_name = unclassified["occupation_major_code"], unclassified["occupation_major_name"]
            green, digital = "0", "0"
            match_method = match["match_method"]
            match_target = match["match_target"]
            target_level = match["target_level"]

        high_confidence_id = small_code if high_confidence_accepted and fallback is None else UNCLASSIFIED_SMALL_CODE

        output_rows.append({
            "source_record_id": str(row.source_record_id),
            "job_title_raw": row.job_title_raw,
            "job_title_normalized": row.job_title_normalized,
            "occupation_id": small_code,
            "occupation_id_high_confidence": high_confidence_id,
            "occupation_small_code": small_code,
            "occupation_small_name": small_name,
            "occupation_fine_code": fine_code,
            "occupation_fine_name": fine_name,
            "occupation_middle_code": middle_code,
            "occupation_middle_name": middle_name,
            "occupation_major_code": major_code,
            "occupation_major_name": major_name,
            "is_green_occupation": green,
            "is_digital_occupation": digital,
            "occupation_match_method": match_method,
            "occupation_match_target": match_target,
            "occupation_target_level": target_level,
            "occupation_score_top1": round(match["top1"], 3),
            "occupation_score_top2": round(match["top2"], 3),
            "occupation_score_margin": round(match["margin"], 3),
            "occupation_confidence": confidence,
            "occupation_status": status,
            "occupation_review_flag": int(review_flag),
            "occupation_rule_consistency": rule_consistency,
            "legacy_occupation_id": legacy["occupation_id"],
            "legacy_occupation_name": legacy["occupation_name"],
            "legacy_rule_id": legacy["rule_id"],
            "legacy_match_text": legacy["match_text"],
            "legacy_confidence": legacy["confidence"],
            "occupation_version": "occupation_dictionary_v0.2_2022_official_small",
        })

    output = pd.DataFrame(output_rows)
    string_columns = [column for column in output.columns if column not in {
        "occupation_score_top1", "occupation_score_top2", "occupation_score_margin", "occupation_review_flag"
    }]
    for column in string_columns:
        output[column] = output[column].astype("string")
    output["occupation_score_top1"] = output["occupation_score_top1"].astype("float32")
    output["occupation_score_top2"] = output["occupation_score_top2"].astype("float32")
    output["occupation_score_margin"] = output["occupation_score_margin"].astype("float32")
    output["occupation_review_flag"] = output["occupation_review_flag"].astype("int8")
    if len(output) != EXPECTED_ROWS or output["source_record_id"].duplicated().any():
        raise RuntimeError("职业试运行输出主键异常")

    temp_path = output_path.with_suffix(".parquet.tmp")
    temp_path.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pandas(output, preserve_index=False), temp_path, compression="zstd")
    os.replace(temp_path, output_path)

    unique_frame = pd.DataFrame([
        {
            "job_title_normalized": title,
            "record_count": int(unique_counts.get(title, 0)),
            "occupation_match_method": result["match_method"],
            "occupation_match_target": result["match_target"],
            "occupation_target_level": result["target_level"],
            "occupation_score_top1": round(result["top1"], 3),
            "occupation_score_top2": round(result["top2"], 3),
            "occupation_score_margin": round(result["margin"], 3),
            "pre_rule_status": result["status"],
            "candidate_small_code": result["candidate"]["occupation_small_code"] if result["candidate"] else "",
            "candidate_small_name": result["candidate"]["occupation_small_name"] if result["candidate"] else "",
        }
        for title, result in title_results.items()
    ])
    pq.write_table(pa.Table.from_pandas(unique_frame, preserve_index=False), unique_path, compression="zstd")

    total = len(output)
    classified = int(output["occupation_id"].ne(UNCLASSIFIED_SMALL_CODE).sum())
    high_confidence_classified = int(output["occupation_id_high_confidence"].ne(UNCLASSIFIED_SMALL_CODE).sum())
    summary_rows: list[dict] = []
    for dimension, series in [
        ("occupation_status", output["occupation_status"]),
        ("occupation_match_method", output["occupation_match_method"]),
        ("occupation_confidence", output["occupation_confidence"]),
        ("occupation_rule_consistency", output["occupation_rule_consistency"]),
        ("occupation_major_code", output["occupation_major_code"]),
    ]:
        for value, count in series.value_counts(dropna=False).items():
            summary_rows.append({"dimension": dimension, "value": value, "count": int(count), "share": round(int(count) / total, 8)})
    summary = pd.DataFrame(summary_rows)
    write_csv(SUMMARY_PATH, summary)

    threshold_rows = []
    for threshold in (70, 80, 90):
        mask = output["occupation_score_top1"].ge(threshold)
        margin_mask = mask & output["occupation_score_margin"].ge(5)
        threshold_rows.append({
            "threshold": threshold,
            "records_score_at_least": int(mask.sum()),
            "share_score_at_least": round(float(mask.mean()), 8),
            "records_score_and_margin5": int(margin_mask.sum()),
            "share_score_and_margin5": round(float(margin_mask.mean()), 8),
        })
    threshold_frame = pd.DataFrame(threshold_rows)
    write_csv(THRESHOLD_PATH, threshold_frame)

    distribution = (
        output.groupby(["occupation_id", "occupation_small_name"], dropna=False)
        .size().rename("count").reset_index().sort_values("count", ascending=False)
    )
    distribution["share"] = distribution["count"] / total
    write_csv(DISTRIBUTION_PATH, distribution)

    unclassified_slice = (
        output.loc[output["occupation_id"].eq(UNCLASSIFIED_SMALL_CODE)]
        .groupby(["job_title_normalized", "occupation_status", "occupation_match_target"], dropna=False)
        .agg(count=("source_record_id", "size"), score=("occupation_score_top1", "max"), margin=("occupation_score_margin", "max"))
        .reset_index().sort_values(["count", "score"], ascending=[False, False]).head(300)
    )
    write_csv(UNCLASSIFIED_PATH, unclassified_slice)
    conflicts = output.loc[output["occupation_status"].eq("fuzzy_rule_conflict"), [
        "source_record_id", "job_title_raw", "job_title_normalized", "occupation_match_target",
        "occupation_score_top1", "occupation_score_margin", "legacy_occupation_id", "legacy_occupation_name",
    ]].head(300)
    write_csv(CONFLICT_PATH, conflicts)
    review = choose_review_sample(output)
    write_csv(REVIEW_PATH, review)

    status_counts = Counter(output["occupation_status"].tolist())
    method_counts = Counter(output["occupation_match_method"].tolist())
    top_unclassified_lines = []
    for row in unclassified_slice.head(20).itertuples(index=False):
        top_unclassified_lines.append(
            f"|{row.job_title_normalized}|{int(row.count):,}|{row.occupation_status}|{row.occupation_match_target}|{row.score:.1f}|{row.margin:.1f}|"
        )
    report = f"""# 2022年职业大典模糊匹配试运行报告 v0.2

结论：程序运行和结构校验通过；结果仍需完成分层人工复核后才能并入正式回归底表。

## 一、试运行规模

- 招聘广告：{total:,}条；
- 标准化岗位名称：{len(unique_titles):,}种；
- 成功生成职业小类`occupation_id`：{classified:,}条，占{classified / total:.2%}；
- 其中高置信度`occupation_id_high_confidence`：{high_confidence_classified:,}条，占{high_confidence_classified / total:.2%}；
- 不便分类`8-00-00`：{total - classified:,}条，占{1 - classified / total:.2%}。

## 二、匹配来源

- 人工别名完全一致：{method_counts.get('exact_manual', 0):,}条；
- 职业大典正式名称完全一致：{method_counts.get('exact_official', 0):,}条；
- 唯一系统变体完全一致：{method_counts.get('exact_systematic', 0):,}条；
- 模糊匹配候选：{method_counts.get('fuzzy_alias', 0):,}条。

## 三、正式采用规则

- 最终`occupation_id`使用职业大典小类代码；
- 完全一致的正式名称、人工别名或唯一系统变体直接保留；
- 模糊匹配只有在第一名分数不低于90、且比第二个小类至少高5分时才自动保留；
- 模糊分数使用标准化岗位名称的Levenshtein整体相似度`RapidFuzz fuzz.ratio`，不使用容易放大短词重合的`WRatio`；
- 高分模糊结果如果与v0.1关键词职业方向冲突，暂不保留，进入人工复核；
- 80—89分只进入复核，70—79分只作诊断，低于70分不匹配；
- 通用标题如“项目经理、产品经理、研发工程师、操作工”不强制归类。

## 四、状态统计

- 完全一致后保留：{status_counts.get('exact_accepted', 0):,}条；
- 高分模糊匹配后保留：{status_counts.get('fuzzy_high_accepted', 0):,}条；
- 旧关键词职业组转小类兜底：{status_counts.get('legacy_group_fallback', 0):,}条；
- 高分但与旧规则冲突：{status_counts.get('fuzzy_rule_conflict', 0):,}条；
- 80—89分待复核：{status_counts.get('score_80_89_review', 0):,}条；
- 70—79分诊断：{status_counts.get('score_70_79_diagnostic', 0):,}条；
- 通用标题拦截：{status_counts.get('generic_title_blocked', 0):,}条。

## 五、未分类高频岗位

|标准化岗位|记录数|状态|第一候选|分数|分差|
|---|---:|---|---|---:|---:|
{chr(10).join(top_unclassified_lines)}

## 六、限制

1. 字符串相似度衡量的是名称接近程度，不等于职业含义一定相同；
2. 只有岗位名称，无法可靠区分“项目经理、研发工程师”等跨行业通用岗位；
3. 别名表中的小类级别别名只支持基准`occupation_id`，不会伪造职业细类；
4. `legacy_group_fallback`属于中置信度扩展结果，建议基准回归同时报告高置信度样本稳健性；
5. 当前自动覆盖率不是准确率。应填写800条分层复核样本后，再报告小类准确率。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")

    manifest = {
        "version": "occupation_dictionary_v0.2_2022_official_small",
        "matcher_version": MATCHER_VERSION,
        "match_scorer": MATCH_SCORER_NAME,
        "status": "pilot_complete_manual_validation_pending",
        "rows": total,
        "unique_normalized_titles": len(unique_titles),
        "classified_rows": classified,
        "classified_share": classified / total,
        "high_confidence_classified_rows": high_confidence_classified,
        "high_confidence_classified_share": high_confidence_classified / total,
        "unclassified_rows": total - classified,
        "dictionary_sha256": sha256(DICTIONARY_PATH),
        "alias_sha256": sha256(ALIAS_PATH),
        "output_sha256": sha256(output_path),
        "output_path": str(output_path),
        "unique_match_path": str(unique_path),
        "threshold": 90,
        "minimum_margin": 5,
        "baseline_occupation_level": "small",
        "unclassified_code": UNCLASSIFIED_SMALL_CODE,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output_path}")
    print(f"ROWS={total}")
    print(f"UNIQUE_TITLES={len(unique_titles)}")
    print(f"CLASSIFIED={classified}")
    print(f"CLASSIFIED_SHARE={classified / total:.6f}")
    print(f"REVIEW_SAMPLE={len(review)}")
    print("OCCUPATION_V02_PILOT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
