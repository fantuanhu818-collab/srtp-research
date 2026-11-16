"""按v0.3方案试跑2022年粗职业分类。

主分类为v0.1的37个职业组。职业名称词典只对关键词规则未分类或冲突的岗位做补漏。
本脚本只写入独立试运行目录，不修改cleaned_v1或confirmed_core_v2。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz import fuzz, process


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
ANCHOR_PATH = PROJECT_ROOT / "config" / "occupation_name_dictionary_v0.3.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
EXPECTED_ROWS = 328_548
VERSION = "occupation_v0.3_coarse_fuzzy_20261116"

SUMMARY_PATH = QC_ROOT / "occupation_v03_2022_summary.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_v03_2022_distribution.csv"
UNCLASSIFIED_PATH = QC_ROOT / "occupation_v03_2022_top_unclassified.csv"
FUZZY_PATH = QC_ROOT / "occupation_v03_2022_fuzzy_accepted.csv"
REVIEW_PATH = QC_ROOT / "occupation_v03_2022_review_sample.csv"
REPORT_PATH = QC_ROOT / "occupation_v03_2022_report.md"

GENERIC_TITLES = {
    "工程师", "技术员", "技术工程师", "管理员", "专员", "助理", "经理", "主管", "总监", "文员",
    "业务经理", "区域经理", "综合管理员", "储备干部", "管培生", "仪表板工程师", "数据线工程师",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_v01_classifier():
    module_path = PROJECT_ROOT / "code" / "python" / "12_pilot_occupation_2022.py"
    spec = importlib.util.spec_from_file_location("occupation_v01_pilot", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入v0.1职业分类器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = load_json(RULE_PATH)
    classifier, _ = module.build_classifier(config)
    return classifier, module.normalize_title, config


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def normalize_v03(value: object, base_normalizer) -> str:
    """补足v0.1中“中高级”等组合职级残留为“中”的清理缺口。"""
    if value is None or pd.isna(value):
        return ""
    raw = re.sub(r"(?:初中高级|中高级|初中级|中高)", "", str(value), flags=re.IGNORECASE)
    return base_normalizer(raw)


def choose_review_sample(frame: pd.DataFrame, target: int = 700) -> pd.DataFrame:
    strata = [
        ("keyword_high", frame["occupation_method"].eq("keyword_rule") & frame["occupation_confidence"].eq("high"), 180),
        ("keyword_medium_or_fallback", frame["occupation_method"].isin(["keyword_rule", "keyword_fallback"]) & frame["occupation_confidence"].ne("high"), 100),
        ("exact_anchor", frame["occupation_method"].eq("exact_anchor"), 120),
        ("fuzzy_anchor", frame["occupation_method"].eq("fuzzy_anchor"), 120),
        ("fuzzy_review", frame["occupation_status"].eq("fuzzy_80_89_review"), 80),
        ("unclassified", frame["occupation_id"].eq("Z99"), 100),
    ]
    chosen: list[pd.DataFrame] = []
    used: set[str] = set()
    for name, condition, number in strata:
        candidates = frame.loc[condition & ~frame["source_record_id"].isin(used)].copy()
        candidates["_sample_hash"] = candidates["source_record_id"].map(stable_hash)
        part = candidates.sort_values("_sample_hash").head(number).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", name)
        chosen.append(part)
        used.update(part["source_record_id"].tolist())
    sample = pd.concat(chosen, ignore_index=True) if chosen else frame.head(0).copy()
    if len(sample) < target:
        remain = frame.loc[~frame["source_record_id"].isin(used)].copy()
        remain["_sample_hash"] = remain["source_record_id"].map(stable_hash)
        part = remain.sort_values("_sample_hash").head(target - len(sample)).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", "fill")
        sample = pd.concat([sample, part], ignore_index=True)
    columns = [
        "review_stratum", "source_record_id", "job_title_raw", "job_title_normalized",
        "occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name",
        "occupation_method", "occupation_match_target", "occupation_score_top1",
        "occupation_score_top2", "occupation_score_margin", "occupation_confidence",
        "occupation_status", "occupation_review_flag", "occupation_rule_id",
    ]
    sample = sample[columns].copy()
    sample["manual_correct"] = ""
    sample["manual_occupation_id"] = ""
    sample["manual_error_reason"] = ""
    sample["manual_notes"] = ""
    return sample


def main() -> int:
    storage = load_json(STORAGE_PATH)
    classifier, normalize_title, config = load_v01_classifier()
    anchors = pd.read_csv(ANCHOR_PATH, dtype="string").fillna("")
    required_anchor_columns = {
        "anchor_title", "anchor_normalized", "occupation_id", "occupation_name",
        "occupation_l1", "occupation_l1_name", "review_status",
    }
    if not required_anchor_columns.issubset(anchors.columns) or anchors.empty:
        raise RuntimeError("v0.3职业名称词典缺少字段或为空")
    duplicate_anchor = anchors.groupby("anchor_normalized")["occupation_id"].nunique()
    if duplicate_anchor.gt(1).any():
        raise RuntimeError("同一词典名称对应多个职业组")
    exact_lookup = anchors.drop_duplicates("anchor_normalized").set_index("anchor_normalized").to_dict("index")
    anchor_choices = anchors["anchor_normalized"].tolist()
    anchor_records = anchors.to_dict("records")
    generic_titles = {normalize_v03(title, normalize_title) for title in GENERIC_TITLES}

    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    output_root = Path(storage["features_root"]) / "occupation_pilot_v0.3"
    output_path = output_root / "jobs_2022_occupation_v0.3.parquet"
    manifest_path = output_root / "manifest_2022.json"
    output_root.mkdir(parents=True, exist_ok=True)

    source = pq.read_table(cleaned_path, columns=["来源记录ID", "招聘岗位", "初级分类"]).to_pandas()
    source = source.rename(columns={
        "来源记录ID": "source_record_id", "招聘岗位": "job_title_raw", "初级分类": "primary_category_raw",
    })
    if len(source) != EXPECTED_ROWS or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗数据行数或主键异常")
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    if set(source["source_record_id"]) != core_ids:
        raise RuntimeError("2022年清洗数据与confirmed_core_v2来源记录ID不一致")
    source["job_title_normalized"] = source["job_title_raw"].map(
        lambda value: normalize_v03(value, normalize_title)
    ).astype("string")

    legacy_cache: dict[tuple[str, str], dict] = {}
    legacy_results: list[dict] = []
    for raw, primary in zip(source["job_title_raw"], source["primary_category_raw"]):
        key = ("" if pd.isna(raw) else str(raw), "" if pd.isna(primary) else str(primary))
        if key not in legacy_cache:
            legacy_cache[key] = classifier(raw, primary)
        legacy_results.append(legacy_cache[key])
    legacy_frame = pd.DataFrame(legacy_results)
    source["legacy_occupation_id"] = legacy_frame["occupation_id"].astype("string")
    source["legacy_occupation_name"] = legacy_frame["occupation_name"].astype("string")
    source["legacy_occupation_l1"] = legacy_frame["occupation_l1"].astype("string")
    source["legacy_occupation_l1_name"] = legacy_frame["occupation_l1_name"].astype("string")
    source["legacy_rule_id"] = legacy_frame["rule_id"].astype("string")
    source["legacy_match_text"] = legacy_frame["match_text"].astype("string")
    source["legacy_confidence"] = legacy_frame["confidence"].astype("string")
    source["legacy_status"] = legacy_frame["status"].astype("string")
    source["legacy_source"] = legacy_frame["source"].astype("string")

    unresolved_titles = source.loc[source["legacy_occupation_id"].eq("Z99"), "job_title_normalized"].drop_duplicates().tolist()
    match_cache: dict[str, dict] = {}
    for position, title in enumerate(unresolved_titles, start=1):
        if not title:
            match_cache[title] = {"method": "unclassified", "target": "", "top1": 0.0, "top2": 0.0, "margin": 0.0, "status": "empty_title", "confidence": "unclassified", "review": 1, "anchor": None}
            continue
        exact = exact_lookup.get(title)
        if exact is not None:
            match_cache[title] = {"method": "exact_anchor", "target": exact["anchor_title"], "top1": 100.0, "top2": 0.0, "margin": 100.0, "status": "exact_anchor_accepted", "confidence": "high", "review": 0, "anchor": exact}
            continue
        if title in generic_titles:
            match_cache[title] = {"method": "unclassified", "target": "", "top1": 0.0, "top2": 0.0, "margin": 0.0, "status": "generic_title_blocked", "confidence": "unclassified", "review": 1, "anchor": None}
            continue
        raw_matches = process.extract(title, anchor_choices, scorer=fuzz.ratio, limit=len(anchor_choices))
        best_by_group: dict[str, tuple[float, dict]] = {}
        for _, score, index in raw_matches:
            anchor = anchor_records[index]
            previous = best_by_group.get(anchor["occupation_id"])
            if previous is None or score > previous[0]:
                best_by_group[anchor["occupation_id"]] = (float(score), anchor)
        ranked = sorted(best_by_group.values(), key=lambda item: (-item[0], item[1]["occupation_id"], item[1]["anchor_normalized"]))
        top1, anchor = ranked[0]
        top2 = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = top1 - top2
        if top1 >= 90 and margin >= 5:
            status, confidence, review, method = "fuzzy_anchor_accepted", "medium", 1, "fuzzy_anchor"
        elif top1 >= 80:
            status, confidence, review, method = "fuzzy_80_89_review", "unclassified", 1, "unclassified"
            anchor = None
        else:
            status, confidence, review, method = "score_below_80", "unclassified", 1, "unclassified"
            anchor = None
        match_cache[title] = {"method": method, "target": ranked[0][1]["anchor_title"], "top1": top1, "top2": top2, "margin": margin, "status": status, "confidence": confidence, "review": review, "anchor": anchor}
        if position % 10_000 == 0:
            print(f"FUZZY_PROGRESS={position}/{len(unresolved_titles)}", flush=True)

    output_rows: list[dict] = []
    for row in source.itertuples(index=False):
        if row.legacy_occupation_id != "Z99":
            method = "keyword_fallback" if row.legacy_source == "primary_category_fallback" else "keyword_rule"
            status = "keyword_classified"
            confidence = row.legacy_confidence
            result = {
                "occupation_l1": row.legacy_occupation_l1, "occupation_l1_name": row.legacy_occupation_l1_name,
                "occupation_id": row.legacy_occupation_id, "occupation_name": row.legacy_occupation_name,
                "method": method, "target": row.legacy_match_text, "top1": 0.0, "top2": 0.0,
                "margin": 0.0, "status": status, "confidence": confidence,
                "review": int(confidence != "high"), "rule_id": row.legacy_rule_id,
            }
        else:
            match = match_cache[str(row.job_title_normalized)]
            anchor = match["anchor"]
            if anchor is not None:
                result = {
                    "occupation_l1": anchor["occupation_l1"], "occupation_l1_name": anchor["occupation_l1_name"],
                    "occupation_id": anchor["occupation_id"], "occupation_name": anchor["occupation_name"],
                    "method": match["method"], "target": match["target"], "top1": match["top1"], "top2": match["top2"],
                    "margin": match["margin"], "status": match["status"], "confidence": match["confidence"],
                    "review": match["review"], "rule_id": "",
                }
            else:
                result = {
                    "occupation_l1": "Z", "occupation_l1_name": config["l1_names"]["Z"],
                    "occupation_id": "Z99", "occupation_name": config["occupation_names"]["Z99"],
                    "method": "unclassified", "target": match["target"], "top1": match["top1"], "top2": match["top2"],
                    "margin": match["margin"], "status": match["status"], "confidence": "unclassified",
                    "review": 1, "rule_id": "",
                }
        output_rows.append({
            "source_record_id": str(row.source_record_id), "job_title_raw": row.job_title_raw,
            "job_title_normalized": row.job_title_normalized, **result,
            "legacy_occupation_id": row.legacy_occupation_id,
            "legacy_occupation_name": row.legacy_occupation_name,
            "legacy_rule_id": row.legacy_rule_id, "legacy_status": row.legacy_status,
            "occupation_version": VERSION,
        })

    output = pd.DataFrame(output_rows)
    output = output.rename(columns={
        "method": "occupation_method", "target": "occupation_match_target",
        "top1": "occupation_score_top1", "top2": "occupation_score_top2",
        "margin": "occupation_score_margin", "status": "occupation_status",
        "confidence": "occupation_confidence", "review": "occupation_review_flag",
        "rule_id": "occupation_rule_id",
    })
    string_columns = [column for column in output.columns if column not in {"occupation_score_top1", "occupation_score_top2", "occupation_score_margin", "occupation_review_flag"}]
    for column in string_columns:
        output[column] = output[column].astype("string")
    for column in ["occupation_score_top1", "occupation_score_top2", "occupation_score_margin"]:
        output[column] = output[column].astype("float32")
    output["occupation_review_flag"] = output["occupation_review_flag"].astype("int8")
    if len(output) != EXPECTED_ROWS or output["source_record_id"].duplicated().any():
        raise RuntimeError("v0.3输出行数或主键异常")
    if not set(output["occupation_id"].unique()).issubset(set(config["occupation_names"])):
        raise RuntimeError("输出中出现未知职业组")

    temp_path = output_path.with_suffix(".parquet.tmp")
    temp_path.unlink(missing_ok=True)
    pq.write_table(pa.Table.from_pandas(output, preserve_index=False), temp_path, compression="zstd")
    os.replace(temp_path, output_path)

    total = len(output)
    classified = int(output["occupation_id"].ne("Z99").sum())
    summary_rows: list[dict] = []
    for dimension, series in [
        ("occupation_method", output["occupation_method"]),
        ("occupation_status", output["occupation_status"]),
        ("occupation_confidence", output["occupation_confidence"]),
        ("occupation_l1", output["occupation_l1"]),
    ]:
        for value, count in series.value_counts(dropna=False).items():
            summary_rows.append({"dimension": dimension, "value": value, "count": int(count), "share": round(int(count) / total, 8)})
    write_csv(SUMMARY_PATH, pd.DataFrame(summary_rows))
    distribution = output.groupby(["occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name"], dropna=False).size().rename("count").reset_index().sort_values("count", ascending=False)
    distribution["share"] = distribution["count"] / total
    write_csv(DISTRIBUTION_PATH, distribution)
    unclassified = output.loc[output["occupation_id"].eq("Z99")].groupby(["job_title_normalized", "occupation_status", "occupation_match_target"], dropna=False).agg(count=("source_record_id", "size"), score=("occupation_score_top1", "max"), margin=("occupation_score_margin", "max")).reset_index().sort_values(["count", "score"], ascending=[False, False]).head(300)
    write_csv(UNCLASSIFIED_PATH, unclassified)
    fuzzy = output.loc[output["occupation_method"].eq("fuzzy_anchor"), ["source_record_id", "job_title_raw", "job_title_normalized", "occupation_id", "occupation_name", "occupation_match_target", "occupation_score_top1", "occupation_score_top2", "occupation_score_margin", "occupation_review_flag"]].sort_values(["occupation_score_top1", "occupation_score_margin"], ascending=[False, False])
    write_csv(FUZZY_PATH, fuzzy)
    review = choose_review_sample(output)
    write_csv(REVIEW_PATH, review)

    status_counts = Counter(output["occupation_status"].tolist())
    method_counts = Counter(output["occupation_method"].tolist())
    report = f"""# 2022年粗职业分类试运行报告 v0.3

结论：本次试运行以37个职业组作为正式候选`occupation_id`。职业名称词典和模糊匹配只处理原关键词规则未分类或冲突的岗位；本次输出尚未通过人工复核，不能并入正式回归底表。

## 一、试运行规模

- 招聘广告：{total:,}条；
- 已归入37个职业组：{classified:,}条，占{classified / total:.2%}；
- `Z99其他/待分类`：{total - classified:,}条，占{1 - classified / total:.2%}；
- 词典名称数：{len(anchors):,}个；

## 二、分类来源

- 原关键词规则：{method_counts.get('keyword_rule', 0):,}条；
- 初级分类低置信度回退：{method_counts.get('keyword_fallback', 0):,}条；
- 职业名称词典精确匹配：{method_counts.get('exact_anchor', 0):,}条；
- 高分模糊匹配：{method_counts.get('fuzzy_anchor', 0):,}条；
- 未分类：{method_counts.get('unclassified', 0):,}条。

## 三、当前判定规则

- 原关键词规则一旦高置信度分类，模糊匹配不能推翻；
- 原规则未分类或冲突时，先查37组职业名称词典；
- 词典完全一致时直接采用；
- 模糊匹配需第一名至少90分，且领先第二名至少5分；
- 80—89分只保留为人工复核候选，不进入正式职业变量；
- 低于80分、或名称本身过于泛化的岗位保留为`Z99`。

## 四、重点复核

- 高分模糊匹配：{status_counts.get('fuzzy_anchor_accepted', 0):,}条，均标记为需人工抽查；
- 80—89分待复核：{status_counts.get('fuzzy_80_89_review', 0):,}条；
- 本次生成{len(review):,}条分层人工复核样本。

## 五、下一步

1. 优先人工检查`occupation_v03_2022_fuzzy_accepted.csv`中的所有或高频模糊匹配；
2. 填写分层复核样本中的`manual_*`字段；
3. 将确认无误的高频未分类标题加入职业名称词典，再重新试跑；
4. 若项目组决定先生成全量候选结果，仍须在人工复核完成前明确标为“候选职业变量”，不得称为最终冻结版本。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    manifest = {
        "version": VERSION, "status": "pilot_complete_manual_validation_pending", "rows": total,
        "classified_rows": classified, "classified_share": classified / total,
        "anchor_count": len(anchors), "rule_sha256": sha256(RULE_PATH), "anchor_sha256": sha256(ANCHOR_PATH),
        "output_path": str(output_path), "output_sha256": sha256(output_path), "review_sample_rows": len(review),
        "fuzzy_threshold": 90, "minimum_margin": 5, "baseline_occupation_level": "project_37_groups",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output_path}")
    print(f"ROWS={total}")
    print(f"CLASSIFIED={classified}")
    print(f"CLASSIFIED_SHARE={classified / total:.6f}")
    print(f"FUZZY_ACCEPTED={status_counts.get('fuzzy_anchor_accepted', 0)}")
    print(f"OCCUPATION_V03_PILOT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
