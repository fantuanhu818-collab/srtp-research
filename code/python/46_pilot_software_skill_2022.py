"""使用软件技能词典v0.1试跑2022年招聘广告。

本脚本只读取cleaned_v1、confirmed_core_v2和稳定的occupation v0.4.1，输出独立候选
特征与质检材料，不覆盖任何已验收数据。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from software_skill_matcher import DEFAULT_AI_DICTIONARY, SoftwareSkillMatcher


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "software_skill_rules_v0.1.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
VERSION = "software_skill_v0.1_20261119"
EXPECTED_SOURCE_ROWS = 328_548
REVIEW_TARGET = 240

SUMMARY_PATH = QC_ROOT / "software_skill_v01_2022_summary.csv"
RULE_COUNTS_PATH = QC_ROOT / "software_skill_v01_2022_rule_counts.csv"
SUBGROUP_PATH = QC_ROOT / "software_skill_v01_2022_subgroup_distribution.csv"
PLATFORM_PATH = QC_ROOT / "software_skill_v01_2022_platform_distribution.csv"
OCCUPATION_PATH = QC_ROOT / "software_skill_v01_2022_occupation_distribution.csv"
EXAMPLES_PATH = QC_ROOT / "software_skill_v01_2022_rule_examples.csv"
REVIEW_PATH = QC_ROOT / "software_skill_v01_2022_review_sample.csv"
REPORT_PATH = QC_ROOT / "software_skill_v01_2022_report.md"

TECHNICAL_TITLE_PATTERN = re.compile(
    r"工程师|开发|技术|分析|研究|算法|数据|设计|产品|项目|测试|运维|实施|程序|软件|数据库",
    flags=re.IGNORECASE,
)

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("skill_software", pa.int8()),
        pa.field("skill_text_available", pa.bool_(), nullable=False),
        pa.field("software_rule_id", pa.string()),
        pa.field("software_rule_ids", pa.string()),
        pa.field("software_subgroup", pa.string()),
        pa.field("software_subgroups", pa.string()),
        pa.field("software_term_level", pa.string()),
        pa.field("software_term_levels", pa.string()),
        pa.field("software_match_text", pa.string()),
        pa.field("software_evidence", pa.string()),
        pa.field("software_match_source", pa.string()),
        pa.field("software_match_sources", pa.string()),
        pa.field("software_office_basic", pa.int8()),
        pa.field("software_professional", pa.int8()),
        pa.field("software_has_conditional", pa.int8()),
        pa.field("software_title_hit", pa.int8()),
        pa.field("software_hit_count", pa.int16()),
        pa.field("software_rule_version", pa.string(), nullable=False),
    ]
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_frame = frame.copy()
    for column in clean_frame.select_dtypes(include=["object", "string"]).columns:
        clean_frame[column] = clean_frame[column].map(
            lambda value: re.sub(r"[ \t]+(?=\r?\n|$)", "", value)
            if isinstance(value, str)
            else value
        )
    clean_frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def split_values(value: object) -> list[str]:
    if value is None or pd.isna(value) or not str(value):
        return []
    return [item for item in str(value).split("|") if item]


def choose_review_sample(frame: pd.DataFrame) -> pd.DataFrame:
    available = frame.loc[frame["skill_text_available"]].copy()
    conditions = [
        (
            "office_only",
            available["software_office_basic"].eq(1)
            & available["software_professional"].eq(0),
        ),
        (
            "professional_only",
            available["software_office_basic"].eq(0)
            & available["software_professional"].eq(1),
        ),
        (
            "office_and_professional",
            available["software_office_basic"].eq(1)
            & available["software_professional"].eq(1),
        ),
        ("conditional_hit", available["software_has_conditional"].eq(1)),
        (
            "no_hit_technical_title",
            available["skill_software"].eq(0)
            & available["job_title"].str.contains(TECHNICAL_TITLE_PATTERN, na=False),
        ),
        (
            "no_hit_other_title",
            available["skill_software"].eq(0)
            & ~available["job_title"].str.contains(TECHNICAL_TITLE_PATTERN, na=False),
        ),
    ]

    chosen: list[pd.DataFrame] = []
    used: set[str] = set()
    for stratum, condition in conditions:
        candidates = available.loc[condition & ~available["source_record_id"].isin(used)].copy()
        candidates["_sample_hash"] = candidates["source_record_id"].map(stable_hash)
        part = candidates.sort_values("_sample_hash").head(40).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", stratum)
        chosen.append(part)
        used.update(part["source_record_id"].tolist())

    sample = pd.concat(chosen, ignore_index=True)
    if len(sample) < REVIEW_TARGET:
        remaining = available.loc[~available["source_record_id"].isin(used)].copy()
        remaining["_sample_hash"] = remaining["source_record_id"].map(stable_hash)
        fill = remaining.sort_values("_sample_hash").head(REVIEW_TARGET - len(sample))
        fill = fill.drop(columns="_sample_hash")
        fill.insert(0, "review_stratum", "fill")
        sample = pd.concat([sample, fill], ignore_index=True)

    columns = [
        "review_stratum",
        "source_record_id",
        "platform",
        "job_title",
        "job_description",
        "skill_software",
        "software_rule_ids",
        "software_subgroups",
        "software_term_levels",
        "software_match_text",
        "software_evidence",
        "software_office_basic",
        "software_professional",
        "software_has_conditional",
        "software_title_hit",
    ]
    sample = sample[columns].copy()
    sample["manual_software"] = ""
    sample["manual_error_reason"] = ""
    sample["manual_notes"] = ""
    sample["reviewer"] = ""
    return sample


def main() -> int:
    storage = load_json(STORAGE_PATH)
    matcher = SoftwareSkillMatcher(RULE_PATH, DEFAULT_AI_DICTIONARY)
    rules = pd.read_csv(RULE_PATH, dtype="string").fillna("")

    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    occupation_path = (
        Path(storage["features_root"])
        / "occupation_v0.4.1"
        / "jobs_2022_occupation_v0.4.1.parquet"
    )
    output_root = Path(storage["features_root"]) / "software_skill_pilot_v0.1"
    evidence_root = Path(storage["evidence_root"]) / "software_skill_pilot_v0.1"
    output_path = output_root / "jobs_2022_software_skill_v0.1.parquet"
    evidence_path = evidence_root / "software_skill_hits_2022_v0.1.parquet"
    manifest_path = output_root / "manifest_2022.json"
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    QC_ROOT.mkdir(parents=True, exist_ok=True)

    source = pq.read_table(
        cleaned_path,
        columns=["来源记录ID", "招聘岗位", "职位描述", "来源"],
    ).to_pandas()
    source = source.rename(
        columns={
            "来源记录ID": "source_record_id",
            "招聘岗位": "job_title",
            "职位描述": "job_description",
            "来源": "platform",
        }
    )
    if len(source) != EXPECTED_SOURCE_ROWS or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗数据行数或主键异常")

    core_ids = set(
        pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist()
    )
    source = source.loc[source["source_record_id"].isin(core_ids)].copy()
    if len(source) != len(core_ids) or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗数据无法与confirmed_core_v2一一对应")

    results: list[dict[str, object]] = []
    hit_rows: list[dict[str, object]] = []
    for position, (record_id, title, description) in enumerate(
        zip(source["source_record_id"], source["job_title"], source["job_description"]),
        start=1,
    ):
        result = matcher.classify(title, description)
        hits = result.pop("software_hits")
        for hit in hits:
            hit_rows.append({"source_record_id": record_id, **hit})
        results.append(result)
        if position % 50_000 == 0:
            print(f"SOFTWARE_PROGRESS={position}/{len(source)}", flush=True)

    result_frame = pd.DataFrame(results)
    for column in [
        "skill_software",
        "software_office_basic",
        "software_professional",
        "software_has_conditional",
        "software_title_hit",
    ]:
        source[column] = pd.array(result_frame[column], dtype="Int8")
    source["skill_text_available"] = result_frame["skill_text_available"].astype(bool)
    for column in [
        "software_rule_id",
        "software_rule_ids",
        "software_subgroup",
        "software_subgroups",
        "software_term_level",
        "software_term_levels",
        "software_match_text",
        "software_evidence",
        "software_match_source",
        "software_match_sources",
    ]:
        source[column] = result_frame[column].astype("string")
    source["software_hit_count"] = result_frame["software_hit_count"].astype("int16")
    source["software_rule_version"] = VERSION

    feature_columns = [field.name for field in OUTPUT_SCHEMA]
    feature_frame = source[feature_columns].copy()
    table = pa.Table.from_pandas(feature_frame, schema=OUTPUT_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path, compression="zstd")

    hit_frame = pd.DataFrame(hit_rows)
    if hit_frame.empty:
        raise RuntimeError("软件技能试跑没有产生任何命中")
    pq.write_table(pa.Table.from_pandas(hit_frame, preserve_index=False), evidence_path, compression="zstd")

    total = len(source)
    available_count = int(source["skill_text_available"].sum())
    positive_count = int(source["skill_software"].eq(1).sum())
    office_count = int(source["software_office_basic"].eq(1).sum())
    professional_count = int(source["software_professional"].eq(1).sum())
    office_only_count = int(
        (source["software_office_basic"].eq(1) & source["software_professional"].eq(0)).sum()
    )
    professional_only_count = int(
        (source["software_office_basic"].eq(0) & source["software_professional"].eq(1)).sum()
    )
    both_count = int(
        (source["software_office_basic"].eq(1) & source["software_professional"].eq(1)).sum()
    )
    conditional_count = int(source["software_has_conditional"].eq(1).sum())
    title_count = int(source["software_title_hit"].eq(1).sum())

    summary = pd.DataFrame(
        [
            {"metric": "total_records", "count": total, "share": 1.0},
            {"metric": "skill_text_available", "count": available_count, "share": available_count / total},
            {"metric": "skill_text_unavailable", "count": total - available_count, "share": (total - available_count) / total},
            {"metric": "skill_software_1", "count": positive_count, "share": positive_count / total},
            {"metric": "software_office_basic_1", "count": office_count, "share": office_count / total},
            {"metric": "software_professional_1", "count": professional_count, "share": professional_count / total},
            {"metric": "office_only", "count": office_only_count, "share": office_only_count / total},
            {"metric": "professional_only", "count": professional_only_count, "share": professional_only_count / total},
            {"metric": "office_and_professional", "count": both_count, "share": both_count / total},
            {"metric": "conditional_hit", "count": conditional_count, "share": conditional_count / total},
            {"metric": "title_hit", "count": title_count, "share": title_count / total},
        ]
    )
    write_csv(SUMMARY_PATH, summary)

    rule_counter = Counter(hit_frame["rule_id"])
    rules["matched_records"] = rules["rule_id"].map(rule_counter).fillna(0).astype(int)
    rules["share_of_all_records"] = rules["matched_records"] / total
    rules["share_of_positive_records"] = rules["matched_records"] / max(positive_count, 1)
    write_csv(RULE_COUNTS_PATH, rules)

    subgroup_rows = []
    for subgroup in sorted(rules["software_subgroup"].unique()):
        count = int(source["software_subgroups"].map(lambda value: subgroup in split_values(value)).sum())
        subgroup_rows.append(
            {
                "software_subgroup": subgroup,
                "matched_records": count,
                "share_of_all_records": count / total,
                "share_of_positive_records": count / max(positive_count, 1),
            }
        )
    write_csv(SUBGROUP_PATH, pd.DataFrame(subgroup_rows))

    platform = (
        source.groupby("platform", dropna=False)
        .agg(
            records=("source_record_id", "size"),
            text_available=("skill_text_available", "sum"),
            software_positive=("skill_software", lambda values: int(values.eq(1).sum())),
            office_positive=("software_office_basic", lambda values: int(values.eq(1).sum())),
            professional_positive=("software_professional", lambda values: int(values.eq(1).sum())),
        )
        .reset_index()
    )
    platform["software_rate"] = platform["software_positive"] / platform["records"]
    platform["office_rate"] = platform["office_positive"] / platform["records"]
    platform["professional_rate"] = platform["professional_positive"] / platform["records"]
    write_csv(PLATFORM_PATH, platform)

    if occupation_path.exists():
        occupation = pq.read_table(
            occupation_path,
            columns=["source_record_id", "occupation_id", "occupation_name"],
        ).to_pandas()
        occupation_joined = source[
            ["source_record_id", "skill_software", "software_office_basic", "software_professional"]
        ].merge(occupation, on="source_record_id", how="left", validate="one_to_one")
        occupation_distribution = (
            occupation_joined.groupby(["occupation_id", "occupation_name"], dropna=False)
            .agg(
                records=("source_record_id", "size"),
                software_positive=("skill_software", lambda values: int(values.eq(1).sum())),
                office_positive=("software_office_basic", lambda values: int(values.eq(1).sum())),
                professional_positive=("software_professional", lambda values: int(values.eq(1).sum())),
            )
            .reset_index()
        )
        occupation_distribution["software_rate"] = (
            occupation_distribution["software_positive"] / occupation_distribution["records"]
        )
        write_csv(OCCUPATION_PATH, occupation_distribution)

    hit_examples = hit_frame.merge(
        source[["source_record_id", "platform", "job_title"]],
        on="source_record_id",
        how="left",
        validate="many_to_one",
    )
    hit_examples["_sample_hash"] = (
        hit_examples["source_record_id"].astype(str) + "|" + hit_examples["rule_id"].astype(str)
    ).map(stable_hash)
    examples = (
        hit_examples.sort_values("_sample_hash")
        .groupby("rule_id", group_keys=False)
        .head(5)
        .drop(columns="_sample_hash")
    )
    examples = examples.merge(
        rules[["rule_id", "standard_term"]], on="rule_id", how="left", validate="many_to_one"
    )
    write_csv(EXAMPLES_PATH, examples)

    review = choose_review_sample(source)
    if len(review) != REVIEW_TARGET or review["source_record_id"].duplicated().any():
        raise RuntimeError("软件技能人工复核样本数量或主键异常")
    write_csv(REVIEW_PATH, review)

    office_generic_count = int(rule_counter.get("SWC007", 0))
    ug_count = int(rule_counter.get("SWE004", 0))
    cloud_count = int(rule_counter.get("SWV009", 0))
    r_count = int(rule_counter.get("SWA008", 0))
    design_count = int(rule_counter.get("SWE011", 0))

    report = f"""# 2022年软件技能变量试运行报告

结论：程序已按软件技能词典v0.1完成2022年候选变量构建。结果仅用于诊断和人工复核，在人工验证前不能称为正式变量。

## 1. 样本和文本

- 回归底表记录：{total:,}条；
- 文本可用于判断：{available_count:,}条（{available_count / total:.2%}）；
- 文本不可判断：{total - available_count:,}条（{(total - available_count) / total:.2%}）。

## 2. 初步识别结果

- `skill_software = 1`：{positive_count:,}条（{positive_count / total:.2%}）；
- 命中基础办公软件：{office_count:,}条（{office_count / total:.2%}）；
- 命中专业软件：{professional_count:,}条（{professional_count / total:.2%}）；
- 仅基础办公软件：{office_only_count:,}条（{office_only_count / total:.2%}）；
- 仅专业软件：{professional_only_count:,}条（{professional_only_count / total:.2%}）；
- 两类均命中：{both_count:,}条（{both_count / total:.2%}）；
- 存在条件词命中：{conditional_count:,}条（{conditional_count / total:.2%}）；
- 岗位名称存在明确软件词：{title_count:,}条（{title_count / total:.2%}）。

以上比例是词典规则产生的候选覆盖，不等于人工确认后的真实软件技能需求比例。基础办公软件按照项目组确认口径进入主变量，但单独保留子类供检查和后续稳健性分析。

## 3. 处理口径

- 岗位名称中的明确软件名称可以命中，宽泛名称不能单独命中；
- Office、Word、Excel、PowerPoint和WPS计入软件技能；
- TensorFlow、PyTorch、Keras、OpenCV等AI专属工具不进入软件词典；
- 复用AI v1.0的分句、公司介绍和否定表达口径；
- 保存全部规则ID，并将逐次命中证据另存为稀疏证据表。

## 4. 试跑中发现并修正的问题

- 为UG增加英文边界，避免误命中UGC、bug和Debug；最终命中{ug_count:,}条；
- 删除歧义极大的裸GCP，只保留Google Cloud Platform和中文云平台名称；云平台规则最终命中{cloud_count:,}条；
- 将裸R限制在明确技能要求或技能列表中，排除邮箱字符和GR&R；R语言规则最终命中{r_count:,}条；
- 补充Photoshop、Illustrator、Premiere、After Effects等设计软件，最终命中{design_count:,}条；
- “办公软件技能”条件规则命中{office_generic_count:,}条，是当前最高频规则，必须作为人工复核重点。

## 5. 输出

- 候选特征：`{output_path}`；
- 稀疏证据：`{evidence_path}`；
- 汇总：`{SUMMARY_PATH.relative_to(PROJECT_ROOT)}`；
- 规则命中：`{RULE_COUNTS_PATH.relative_to(PROJECT_ROOT)}`；
- 子类分布：`{SUBGROUP_PATH.relative_to(PROJECT_ROOT)}`；
- 平台分布：`{PLATFORM_PATH.relative_to(PROJECT_ROOT)}`；
- 职业分布：`{OCCUPATION_PATH.relative_to(PROJECT_ROOT)}`；
- 规则例子：`{EXAMPLES_PATH.relative_to(PROJECT_ROOT)}`；
- 诊断复核样本：`{REVIEW_PATH.relative_to(PROJECT_ROOT)}`。

## 6. 下一步

1. 检查高频词、基础办公软件占比和典型切片；
2. 修正明显误判后，与认知、社交候选结果生成统一人工复核工作簿；
3. 人工验证完成后再运行2018—2025年全样本。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")

    manifest = {
        "version": VERSION,
        "year": 2022,
        "source_path": str(cleaned_path),
        "core_path": str(core_path),
        "occupation_path": str(occupation_path),
        "rule_path": str(RULE_PATH),
        "rule_sha256": sha256(RULE_PATH),
        "ai_context_path": str(DEFAULT_AI_DICTIONARY),
        "ai_context_sha256": sha256(DEFAULT_AI_DICTIONARY),
        "output_path": str(output_path),
        "evidence_path": str(evidence_path),
        "output_rows": total,
        "hit_rows": len(hit_frame),
        "review_rows": len(review),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"SOFTWARE_SKILL_2022_ROWS={total}")
    print(f"SOFTWARE_SKILL_2022_POSITIVE={positive_count}")
    print(f"SOFTWARE_SKILL_2022_OFFICE={office_count}")
    print(f"SOFTWARE_SKILL_2022_PROFESSIONAL={professional_count}")
    print(f"SOFTWARE_SKILL_2022_HITS={len(hit_frame)}")
    print(f"SOFTWARE_SKILL_2022_REVIEW={len(review)}")
    print("SOFTWARE_SKILL_2022=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
