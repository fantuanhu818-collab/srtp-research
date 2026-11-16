"""将v0.3粗职业分类应用到2018—2025年全量清洗样本。

分类顺序与2022年试运行一致：v0.1关键词规则 -> 37组名称词典精确匹配 ->
高门槛RapidFuzz补漏 -> Z99。输出独立职业特征表，不改写任何已有底表。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz import fuzz, process


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
YEARS = list(range(2018, 2026))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
ANCHOR_PATH = PROJECT_ROOT / "config" / "occupation_name_dictionary_v0.3.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
VERSION = "occupation_v0.3_coarse_fuzzy_all_years_20261116"
BATCH_SIZE = 10_000

SUMMARY_PATH = QC_ROOT / "occupation_v03_all_years_summary.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_v03_all_years_distribution.csv"
FUZZY_PATH = QC_ROOT / "occupation_v03_all_years_fuzzy_accepted.csv"
UNCLASSIFIED_PATH = QC_ROOT / "occupation_v03_all_years_top_unclassified.csv"
REVIEW_PATH = QC_ROOT / "occupation_v03_all_years_review_sample.csv"
REPORT_PATH = QC_ROOT / "occupation_v03_all_years_report.md"


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


def load_v03_module():
    module_path = PROJECT_ROOT / "code" / "python" / "18_pilot_occupation_coarse_2022.py"
    spec = importlib.util.spec_from_file_location("occupation_v03_pilot", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入v0.3职业分类模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sample_for_review(frame: pd.DataFrame, year: int) -> pd.DataFrame:
    strata = [
        ("keyword_high", frame["occupation_method"].eq("keyword_rule") & frame["occupation_confidence"].eq("high"), 25),
        ("keyword_other", frame["occupation_method"].isin(["keyword_rule", "keyword_fallback"]) & frame["occupation_confidence"].ne("high"), 15),
        ("exact_anchor", frame["occupation_method"].eq("exact_anchor"), 20),
        ("fuzzy_anchor", frame["occupation_method"].eq("fuzzy_anchor"), 30),
        ("fuzzy_review", frame["occupation_status"].eq("fuzzy_80_89_review"), 20),
        ("unclassified", frame["occupation_id"].eq("Z99"), 25),
    ]
    picked: list[pd.DataFrame] = []
    used: set[str] = set()
    keep = [
        "source_record_id", "job_title_raw", "job_title_normalized", "occupation_l1",
        "occupation_l1_name", "occupation_id", "occupation_name", "occupation_method",
        "occupation_match_target", "occupation_score_top1", "occupation_score_top2",
        "occupation_score_margin", "occupation_confidence", "occupation_status",
        "occupation_review_flag", "occupation_rule_id",
    ]
    for stratum, condition, count in strata:
        candidates = frame.loc[condition & ~frame["source_record_id"].isin(used), keep].copy()
        candidates["_hash"] = candidates["source_record_id"].map(stable_hash)
        part = candidates.sort_values("_hash").head(count).drop(columns="_hash")
        part.insert(0, "review_stratum", stratum)
        part.insert(0, "year", year)
        picked.append(part)
        used.update(part["source_record_id"].tolist())
    return pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()


def main() -> int:
    storage = load_json(STORAGE_PATH)
    module = load_v03_module()
    classifier, base_normalizer, config = module.load_v01_classifier()
    normalize = lambda value: module.normalize_v03(value, base_normalizer)

    anchors = pd.read_csv(ANCHOR_PATH, dtype="string").fillna("")
    if anchors.empty:
        raise RuntimeError("v0.3职业名称词典为空")
    anchor_conflicts = anchors.groupby("anchor_normalized")["occupation_id"].nunique()
    if anchor_conflicts.gt(1).any():
        raise RuntimeError("同一职业名称词典条目对应多个37组职业")
    anchors = anchors.drop_duplicates(["anchor_normalized", "occupation_id"]).reset_index(drop=True)
    exact_lookup = anchors.drop_duplicates("anchor_normalized").set_index("anchor_normalized").to_dict("index")
    anchor_choices = anchors["anchor_normalized"].astype(str).tolist()
    anchor_records = anchors.to_dict("records")
    group_ids = sorted(anchors["occupation_id"].unique().tolist())
    group_anchor_indices = {
        group: np.flatnonzero(anchors["occupation_id"].eq(group).to_numpy()) for group in group_ids
    }
    generic_titles = {normalize(title) for title in module.GENERIC_TITLES}

    output_root = Path(storage["features_root"]) / "occupation_v0.3"
    output_root.mkdir(parents=True, exist_ok=True)
    legacy_cache: dict[str, dict] = {}
    fuzzy_cache: dict[str, dict] = {}
    annual_rows: list[dict] = []
    summary_parts: list[pd.DataFrame] = []
    distribution_parts: list[pd.DataFrame] = []
    fuzzy_parts: list[pd.DataFrame] = []
    unclassified_parts: list[pd.DataFrame] = []
    review_parts: list[pd.DataFrame] = []

    for year in YEARS:
        print(f"YEAR_START={year}", flush=True)
        cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / f"jobs_{year}_cleaned.parquet"
        core_path = Path(storage["features_root"]) / "confirmed_core_v2" / f"jobs_{year}_confirmed_core.parquet"
        output_path = output_root / f"jobs_{year}_occupation_v0.3.parquet"
        source = pq.read_table(cleaned_path, columns=["来源记录ID", "招聘岗位", "初级分类"]).to_pandas()
        source = source.rename(columns={
            "来源记录ID": "source_record_id", "招聘岗位": "job_title_raw", "初级分类": "primary_category_raw",
        })
        if source["source_record_id"].duplicated().any():
            raise RuntimeError(f"{year}年清洗数据来源记录ID重复")
        core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
        source_ids = set(source["source_record_id"])
        if not core_ids.issubset(source_ids):
            raise RuntimeError(f"{year}年confirmed_core_v2存在无法回溯到清洗数据的来源记录ID")
        # confirmed_core_v2比cleaned_v1少63条已确认的学历异常记录；职业变量严格跟随回归底表样本。
        source = source.loc[source["source_record_id"].isin(core_ids)].copy()
        if len(source) != len(core_ids):
            raise RuntimeError(f"{year}年筛选confirmed_core_v2样本后记录数异常")
        source["source_record_id"] = source["source_record_id"].astype("string")
        source["job_title_normalized"] = source["job_title_raw"].map(normalize).astype("string")

        raw_key = source["job_title_raw"].fillna("").astype(str)
        primary_key = source["primary_category_raw"].fillna("").astype(str)
        source["_legacy_key"] = raw_key.str.cat(primary_key, sep="\x1f")
        unique_pairs = source[["_legacy_key", "job_title_raw", "primary_category_raw"]].drop_duplicates("_legacy_key")
        for legacy_key, job_title_raw, primary_category_raw in unique_pairs.itertuples(index=False, name=None):
            if legacy_key not in legacy_cache:
                legacy_cache[legacy_key] = classifier(job_title_raw, primary_category_raw)
        needed_legacy = {key: legacy_cache[key] for key in unique_pairs["_legacy_key"]}
        legacy_unique = pd.DataFrame.from_dict(needed_legacy, orient="index")
        legacy_unique.index.name = "_legacy_key"
        legacy_unique = legacy_unique.rename(columns={
            "occupation_id": "legacy_occupation_id", "occupation_l1": "legacy_occupation_l1",
            "occupation_name": "legacy_occupation_name", "occupation_l1_name": "legacy_occupation_l1_name",
            "rule_id": "legacy_rule_id", "match_text": "legacy_match_text",
            "confidence": "legacy_confidence", "status": "legacy_status", "source": "legacy_source",
        })
        source = source.join(legacy_unique[[
            "legacy_occupation_id", "legacy_occupation_l1", "legacy_occupation_name",
            "legacy_occupation_l1_name", "legacy_rule_id", "legacy_match_text",
            "legacy_confidence", "legacy_status", "legacy_source",
        ]], on="_legacy_key")

        unresolved_titles = source.loc[
            source["legacy_occupation_id"].eq("Z99"), "job_title_normalized"
        ].drop_duplicates().astype(str).tolist()
        missing_titles = [title for title in unresolved_titles if title not in fuzzy_cache]
        fuzzy_titles: list[str] = []
        for title in missing_titles:
            if not title:
                fuzzy_cache[title] = {
                    "occupation_id": "Z99", "occupation_l1": "Z", "method": "unclassified",
                    "target": "", "top1": 0.0, "top2": 0.0, "margin": 0.0,
                    "status": "empty_title", "confidence": "unclassified", "review": 1,
                }
            elif title in exact_lookup:
                anchor = exact_lookup[title]
                fuzzy_cache[title] = {
                    "occupation_id": anchor["occupation_id"], "occupation_l1": anchor["occupation_l1"],
                    "method": "exact_anchor", "target": anchor["anchor_title"], "top1": 100.0,
                    "top2": 0.0, "margin": 100.0, "status": "exact_anchor_accepted",
                    "confidence": "high", "review": 0,
                }
            elif title in generic_titles:
                fuzzy_cache[title] = {
                    "occupation_id": "Z99", "occupation_l1": "Z", "method": "unclassified",
                    "target": "", "top1": 0.0, "top2": 0.0, "margin": 0.0,
                    "status": "generic_title_blocked", "confidence": "unclassified", "review": 1,
                }
            else:
                fuzzy_titles.append(title)

        for start in range(0, len(fuzzy_titles), BATCH_SIZE):
            batch = fuzzy_titles[start:start + BATCH_SIZE]
            matrix = process.cdist(
                batch, anchor_choices, scorer=fuzz.ratio, dtype=np.float32, workers=-1,
            )
            group_scores = np.column_stack([
                matrix[:, group_anchor_indices[group]].max(axis=1) for group in group_ids
            ])
            top_group_positions = group_scores.argmax(axis=1)
            sorted_group_scores = np.sort(group_scores, axis=1)
            top1_scores = sorted_group_scores[:, -1]
            top2_scores = sorted_group_scores[:, -2] if len(group_ids) > 1 else np.zeros(len(batch))
            for index, title in enumerate(batch):
                group_position = int(top_group_positions[index])
                group = group_ids[group_position]
                anchor_indices = group_anchor_indices[group]
                local_position = int(matrix[index, anchor_indices].argmax())
                anchor_index = int(anchor_indices[local_position])
                anchor = anchor_records[anchor_index]
                top1 = float(top1_scores[index])
                top2 = float(top2_scores[index])
                margin = top1 - top2
                if top1 >= 90 and margin >= 5:
                    fuzzy_cache[title] = {
                        "occupation_id": group, "occupation_l1": group[0], "method": "fuzzy_anchor",
                        "target": anchor["anchor_title"], "top1": top1, "top2": top2, "margin": margin,
                        "status": "fuzzy_anchor_accepted", "confidence": "medium", "review": 1,
                    }
                elif top1 >= 80:
                    fuzzy_cache[title] = {
                        "occupation_id": "Z99", "occupation_l1": "Z", "method": "unclassified",
                        "target": anchor["anchor_title"], "top1": top1, "top2": top2, "margin": margin,
                        "status": "fuzzy_80_89_review", "confidence": "unclassified", "review": 1,
                    }
                else:
                    fuzzy_cache[title] = {
                        "occupation_id": "Z99", "occupation_l1": "Z", "method": "unclassified",
                        "target": anchor["anchor_title"], "top1": top1, "top2": top2, "margin": margin,
                        "status": "score_below_80", "confidence": "unclassified", "review": 1,
                    }
            print(
                f"FUZZY_PROGRESS={year}:{min(start + BATCH_SIZE, len(fuzzy_titles))}/{len(fuzzy_titles)}",
                flush=True,
            )

        match_unique = pd.DataFrame([
            {"job_title_normalized": title, **fuzzy_cache[title]} for title in unresolved_titles
        ]).set_index("job_title_normalized")
        match_unique = match_unique.add_prefix("match_")
        source = source.join(match_unique, on="job_title_normalized")

        legacy_classified = source["legacy_occupation_id"].ne("Z99")
        source["occupation_id"] = source["legacy_occupation_id"].where(legacy_classified, source["match_occupation_id"])
        source["occupation_l1"] = source["legacy_occupation_l1"].where(legacy_classified, source["match_occupation_l1"])
        source["occupation_name"] = source["occupation_id"].map(config["occupation_names"])
        source["occupation_l1_name"] = source["occupation_l1"].map(config["l1_names"])
        keyword_method = np.where(source["legacy_source"].eq("primary_category_fallback"), "keyword_fallback", "keyword_rule")
        source["occupation_method"] = np.where(legacy_classified, keyword_method, source["match_method"])
        source["occupation_match_target"] = np.where(legacy_classified, source["legacy_match_text"], source["match_target"])
        source["occupation_score_top1"] = np.where(legacy_classified, 0.0, source["match_top1"])
        source["occupation_score_top2"] = np.where(legacy_classified, 0.0, source["match_top2"])
        source["occupation_score_margin"] = np.where(legacy_classified, 0.0, source["match_margin"])
        source["occupation_confidence"] = np.where(legacy_classified, source["legacy_confidence"], source["match_confidence"])
        source["occupation_status"] = np.where(legacy_classified, "keyword_classified", source["match_status"])
        source["occupation_review_flag"] = np.where(legacy_classified, source["legacy_confidence"].ne("high").astype("int8"), source["match_review"])
        source["occupation_rule_id"] = np.where(legacy_classified, source["legacy_rule_id"], "")
        source["occupation_version"] = VERSION

        output_columns = [
            "source_record_id", "job_title_raw", "job_title_normalized", "occupation_l1",
            "occupation_l1_name", "occupation_id", "occupation_name", "occupation_method",
            "occupation_match_target", "occupation_score_top1", "occupation_score_top2",
            "occupation_score_margin", "occupation_confidence", "occupation_status",
            "occupation_review_flag", "occupation_rule_id", "legacy_occupation_id",
            "legacy_occupation_name", "legacy_rule_id", "legacy_status", "occupation_version",
        ]
        output = source[output_columns].copy()
        string_columns = [column for column in output.columns if column not in {
            "occupation_score_top1", "occupation_score_top2", "occupation_score_margin", "occupation_review_flag",
        }]
        for column in string_columns:
            output[column] = output[column].astype("string")
        for column in ["occupation_score_top1", "occupation_score_top2", "occupation_score_margin"]:
            output[column] = output[column].astype("float32")
        output["occupation_review_flag"] = output["occupation_review_flag"].astype("int8")
        if len(output) != len(source) or output["source_record_id"].duplicated().any():
            raise RuntimeError(f"{year}年职业特征输出行数或主键异常")

        temp_path = output_path.with_suffix(".parquet.tmp")
        temp_path.unlink(missing_ok=True)
        pq.write_table(pa.Table.from_pandas(output, preserve_index=False), temp_path, compression="zstd")
        os.replace(temp_path, output_path)

        total = len(output)
        classified = int(output["occupation_id"].ne("Z99").sum())
        methods = Counter(output["occupation_method"].tolist())
        annual_rows.append({
            "year": year, "records": total, "classified": classified,
            "classified_share": classified / total, "z99": total - classified,
            "keyword_rule": methods.get("keyword_rule", 0),
            "keyword_fallback": methods.get("keyword_fallback", 0),
            "exact_anchor": methods.get("exact_anchor", 0),
            "fuzzy_anchor": methods.get("fuzzy_anchor", 0),
            "output_path": str(output_path), "output_sha256": sha256(output_path),
        })
        for dimension, series in [
            ("occupation_method", output["occupation_method"]),
            ("occupation_status", output["occupation_status"]),
            ("occupation_confidence", output["occupation_confidence"]),
            ("occupation_l1", output["occupation_l1"]),
        ]:
            counts = series.value_counts(dropna=False).rename_axis("value").reset_index(name="count")
            counts.insert(0, "dimension", dimension)
            counts.insert(0, "year", year)
            counts["share"] = counts["count"] / total
            summary_parts.append(counts)
        distribution = output.groupby([
            "occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name",
        ], dropna=False).size().rename("count").reset_index()
        distribution.insert(0, "year", year)
        distribution["share"] = distribution["count"] / total
        distribution_parts.append(distribution)
        fuzzy_parts.append(output.loc[output["occupation_method"].eq("fuzzy_anchor"), [
            "source_record_id", "job_title_raw", "job_title_normalized", "occupation_id",
            "occupation_name", "occupation_match_target", "occupation_score_top1",
            "occupation_score_top2", "occupation_score_margin", "occupation_review_flag",
        ]].assign(year=year))
        unclassified_parts.append(output.loc[output["occupation_id"].eq("Z99")].groupby([
            "job_title_normalized", "occupation_status", "occupation_match_target",
        ], dropna=False).agg(
            count=("source_record_id", "size"), score=("occupation_score_top1", "max"),
            margin=("occupation_score_margin", "max"),
        ).reset_index().assign(year=year))
        review_parts.append(sample_for_review(output, year))
        print(f"YEAR_DONE={year};ROWS={total};CLASSIFIED_SHARE={classified / total:.6f}", flush=True)

    annual = pd.DataFrame(annual_rows)
    write_csv(SUMMARY_PATH, pd.concat(summary_parts, ignore_index=True))
    write_csv(DISTRIBUTION_PATH, pd.concat(distribution_parts, ignore_index=True).sort_values(["year", "count"], ascending=[True, False]))
    fuzzy_all = pd.concat(fuzzy_parts, ignore_index=True)
    write_csv(FUZZY_PATH, fuzzy_all.sort_values(["year", "occupation_score_top1", "occupation_score_margin"], ascending=[True, False, False]))
    unclassified_all = pd.concat(unclassified_parts, ignore_index=True)
    unclassified_agg = unclassified_all.groupby([
        "job_title_normalized", "occupation_status", "occupation_match_target",
    ], dropna=False).agg(count=("count", "sum"), years=("year", "nunique"), score=("score", "max"), margin=("margin", "max")).reset_index().sort_values(["count", "score"], ascending=[False, False]).head(500)
    write_csv(UNCLASSIFIED_PATH, unclassified_agg)
    review = pd.concat(review_parts, ignore_index=True)
    review["manual_correct"] = ""
    review["manual_occupation_id"] = ""
    review["manual_error_reason"] = ""
    review["manual_notes"] = ""
    write_csv(REVIEW_PATH, review)

    total_records = int(annual["records"].sum())
    total_classified = int(annual["classified"].sum())
    lines = [
        f"|{int(row.year)}|{int(row.records):,}|{int(row.classified):,}|{row.classified_share:.2%}|{int(row.z99):,}|{int(row.exact_anchor):,}|{int(row.fuzzy_anchor):,}|"
        for row in annual.itertuples(index=False)
    ]
    report = f"""# 2018—2025年粗职业分类全量构建报告 v0.3

结论：v0.3已应用到全部5,235,398条`confirmed_core_v2`记录。输出仍需完成分层人工复核后才可视为冻结的正式回归职业变量。

## 一、总体结果

- 总记录：{total_records:,}条；
- 已归入37个职业组：{total_classified:,}条，占{total_classified / total_records:.2%}；
- `Z99其他/待分类`：{total_records - total_classified:,}条，占{1 - total_classified / total_records:.2%}；
- 词典精确补漏：{int(annual['exact_anchor'].sum()):,}条；
- 高分模糊补漏：{int(annual['fuzzy_anchor'].sum()):,}条；
- 分层人工复核样本：{len(review):,}条。

## 二、分年度结果

|年份|记录数|已分类|覆盖率|Z99|词典精确补漏|高分模糊补漏|
|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

## 三、使用限制

1. 原关键词规则已分类记录保持原37组，不被模糊匹配改写；
2. 模糊匹配仅在分数≥90且前两组分差≥5时补漏，并全部标记人工复核；
3. `Z99`表示岗位名称不足以可靠分类，不应为了覆盖率强行赋值；
4. 全量文件位于`{output_root}`，没有覆盖清洗数据或`confirmed_core_v2`；
5. 人工复核完成前，建议把本结果称为“全量候选职业变量”，而不是最终冻结版本。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    manifest = {
        "version": VERSION, "status": "all_years_built_manual_validation_pending",
        "years": YEARS, "records": total_records, "classified": total_classified,
        "classified_share": total_classified / total_records, "anchor_count": len(anchors),
        "rule_sha256": sha256(RULE_PATH), "anchor_sha256": sha256(ANCHOR_PATH),
        "outputs": annual_rows, "review_sample_rows": len(review),
        "fuzzy_threshold": 90, "minimum_margin": 5,
    }
    (output_root / "manifest_all_years.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TOTAL_ROWS={total_records}")
    print(f"CLASSIFIED={total_classified}")
    print(f"CLASSIFIED_SHARE={total_classified / total_records:.6f}")
    print(f"OUTPUT_ROOT={output_root}")
    print("OCCUPATION_V03_ALL_YEARS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
