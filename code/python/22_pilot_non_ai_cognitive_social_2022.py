"""试跑2022年认知技能和社交技能变量。

本脚本只读取cleaned_v1与confirmed_core_v2，输出独立候选特征、质量检查表和
人工复核样本，不修改任何已验收数据。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "non_ai_skill_rules_v0.1.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
VERSION = "non_ai_cognitive_social_v0.1_20261117"
EXPECTED_SOURCE_ROWS = 328_548
REVIEW_TARGET = 240

SUMMARY_PATH = QC_ROOT / "non_ai_skill_v01_2022_summary.csv"
RULE_COUNTS_PATH = QC_ROOT / "non_ai_skill_v01_2022_rule_counts.csv"
PLATFORM_PATH = QC_ROOT / "non_ai_skill_v01_2022_platform_distribution.csv"
EXAMPLES_PATH = QC_ROOT / "non_ai_skill_v01_2022_rule_examples.csv"
REVIEW_PATH = QC_ROOT / "non_ai_skill_v01_2022_review_sample.csv"
REPORT_PATH = QC_ROOT / "non_ai_skill_v01_2022_report.md"

EMPTY_VALUES = {"", "nan", "none", "null", "-", "--", "—"}
NEGATION_PATTERN = re.compile(
    r"不要求|无需|无须|不必|没有要求|能力不限|经验不限|不限|"
    r"not required|no need|without",
    flags=re.IGNORECASE,
)
SENTENCE_SPLIT_PATTERN = re.compile(
    r"(?<=[。！？!?；;])|[\r\n]+|"
    r"(?=岗位职责[:：]?|工作职责[:：]?|任职要求[:：]?|岗位要求[:：]?|职位要求[:：]?|"
    r"福利待遇[:：]?|薪酬福利[:：]?|职位福利[:：]?)|"
    r"(?=(?:\s|^)[一二三四五六七八九十\d]{1,2}[、.．)])"
)
WATERMARK_PATTERN = re.compile(
    r"(?:www\.)?macrodatas\.cn|马[\s-]*克[\s-]*(?:数[\s-]*据[\s-]*网|团[\s-]*队)|"
    r"来源[:：]?\s*马[\s-]*克[\s-]*数据网",
    flags=re.IGNORECASE,
)
PROMOTION_PATTERN = re.compile(
    r"公司简介|企业简介|集团简介|关于我们|公司成立于|本公司成立|公司位于|"
    r"公司主营|公司主要从事|我们是一家|薪酬福利|福利待遇|员工福利|加入我们|"
    r"五险一金|团队氛围|办公环境"
)
TECHNICAL_TITLE_PATTERN = re.compile(r"工程师|开发|技术|分析|研究|算法|数据|设计|产品|项目|测试|运维")

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("skill_cognitive", pa.int8()),
        pa.field("skill_social", pa.int8()),
        pa.field("skill_text_available", pa.bool_(), nullable=False),
        pa.field("cognitive_rule_id", pa.string()),
        pa.field("cognitive_term_level", pa.string()),
        pa.field("cognitive_match_text", pa.string()),
        pa.field("cognitive_evidence", pa.string()),
        pa.field("social_rule_id", pa.string()),
        pa.field("social_term_level", pa.string()),
        pa.field("social_match_text", pa.string()),
        pa.field("social_evidence", pa.string()),
        pa.field("non_ai_skill_version", pa.string(), nullable=False),
    ]
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
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
            if isinstance(value, str) else value
        )
    clean_frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def load_rules() -> pd.DataFrame:
    rules = pd.read_csv(RULE_PATH, dtype="string").fillna("")
    required = {
        "rule_id", "skill_group", "term_level", "standard_term", "pattern",
        "exclude_pattern", "notes",
    }
    if not required.issubset(rules.columns) or rules.empty:
        raise RuntimeError("非AI技能规则表缺少必要字段或为空")
    if rules["rule_id"].duplicated().any():
        raise RuntimeError("非AI技能规则ID重复")
    if not set(rules["skill_group"]).issubset({"cognitive", "social"}):
        raise RuntimeError("规则表包含未允许的技能类别")
    if not set(rules["term_level"]).issubset({"strict", "conditional"}):
        raise RuntimeError("规则表包含未允许的规则层级")
    for pattern in rules["pattern"]:
        re.compile(pattern, flags=re.IGNORECASE)
    for pattern in rules.loc[rules["exclude_pattern"].ne(""), "exclude_pattern"]:
        re.compile(pattern, flags=re.IGNORECASE)
    return rules


def normalize_and_filter_text(value: object) -> tuple[str, bool]:
    if value is None or pd.isna(value):
        return "", False
    text = unicodedata.normalize("NFKC", str(value)).lower()
    text = WATERMARK_PATTERN.sub(" ", text)
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r" +", " ", text)
    if text.strip() in EMPTY_VALUES:
        return "", False

    kept: list[str] = []
    for raw_sentence in SENTENCE_SPLIT_PATTERN.split(text):
        sentence = raw_sentence.strip()
        if not sentence:
            continue
        # 只有宣传/福利标题出现在当前切片开头时才删除。不能因为长段落末尾
        # 出现“五险一金”就把前面的任职要求一并删除。
        if PROMOTION_PATTERN.search(sentence[:40]):
            continue
        kept.append(sentence)
    filtered = "".join(kept).strip()
    visible = re.sub(r"[\W_]+", "", filtered, flags=re.UNICODE)
    return filtered, len(visible) >= 10


def sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    separators = "。！？!?；;\n\r"
    left = start
    while left > 0 and text[left - 1] not in separators:
        left -= 1
    right = end
    while right < len(text) and text[right] not in separators:
        right += 1
    return left, right


def compile_group_matcher(rules: pd.DataFrame, group: str) -> tuple[re.Pattern, dict[str, dict]]:
    records = rules.loc[rules["skill_group"].eq(group)].to_dict("records")
    if not records:
        raise RuntimeError(f"{group}没有可用规则")
    named_parts = [f"(?P<{row['rule_id']}>{row['pattern']})" for row in records]
    return re.compile("|".join(named_parts), flags=re.IGNORECASE), {row["rule_id"]: row for row in records}


def find_valid_match(text: str, matcher: re.Pattern, rule_lookup: dict[str, dict]) -> dict:
    for match in matcher.finditer(text):
        rule_id = match.lastgroup
        if rule_id is None:
            continue
        rule = rule_lookup[rule_id]
        left, right = sentence_bounds(text, match.start(), match.end())
        sentence = text[left:right].strip()
        local_before = text[max(left, match.start() - 12):match.start()]
        if NEGATION_PATTERN.search(local_before):
            continue
        exclude_pattern = rule["exclude_pattern"]
        if exclude_pattern and re.search(exclude_pattern, sentence, flags=re.IGNORECASE):
            continue
        return {
            "value": 1,
            "rule_id": rule_id,
            "term_level": rule["term_level"],
            "match_text": match.group(0),
            "evidence": sentence[:500],
        }
    return {"value": 0, "rule_id": "", "term_level": "", "match_text": "", "evidence": ""}


def choose_review_sample(frame: pd.DataFrame) -> pd.DataFrame:
    available = frame.loc[frame["skill_text_available"]].copy()
    conditions = [
        ("cognitive_only", available["skill_cognitive"].eq(1) & available["skill_social"].eq(0), 40),
        ("social_only", available["skill_cognitive"].eq(0) & available["skill_social"].eq(1), 40),
        ("both_positive", available["skill_cognitive"].eq(1) & available["skill_social"].eq(1), 40),
        (
            "conditional_hit",
            available["cognitive_term_level"].eq("conditional")
            | available["social_term_level"].eq("conditional"),
            40,
        ),
        (
            "neither_technical_title",
            available["skill_cognitive"].eq(0)
            & available["skill_social"].eq(0)
            & available["job_title"].str.contains(TECHNICAL_TITLE_PATTERN, na=False),
            40,
        ),
        (
            "neither_other_title",
            available["skill_cognitive"].eq(0)
            & available["skill_social"].eq(0)
            & ~available["job_title"].str.contains(TECHNICAL_TITLE_PATTERN, na=False),
            40,
        ),
    ]
    chosen: list[pd.DataFrame] = []
    used: set[str] = set()
    for stratum, condition, number in conditions:
        candidates = available.loc[condition & ~available["source_record_id"].isin(used)].copy()
        candidates["_sample_hash"] = candidates["source_record_id"].map(stable_hash)
        part = candidates.sort_values("_sample_hash").head(number).drop(columns="_sample_hash")
        part.insert(0, "review_stratum", stratum)
        chosen.append(part)
        used.update(part["source_record_id"].tolist())
    sample = pd.concat(chosen, ignore_index=True)
    if len(sample) < REVIEW_TARGET:
        remaining = available.loc[~available["source_record_id"].isin(used)].copy()
        remaining["_sample_hash"] = remaining["source_record_id"].map(stable_hash)
        fill = remaining.sort_values("_sample_hash").head(REVIEW_TARGET - len(sample)).drop(columns="_sample_hash")
        fill.insert(0, "review_stratum", "fill")
        sample = pd.concat([sample, fill], ignore_index=True)

    columns = [
        "review_stratum", "source_record_id", "platform", "job_title", "job_description",
        "skill_cognitive", "cognitive_rule_id", "cognitive_term_level", "cognitive_match_text",
        "cognitive_evidence", "skill_social", "social_rule_id", "social_term_level",
        "social_match_text", "social_evidence",
    ]
    sample = sample[columns].copy()
    sample["manual_cognitive"] = ""
    sample["manual_social"] = ""
    sample["manual_error_reason"] = ""
    sample["manual_notes"] = ""
    sample["reviewer"] = ""
    return sample


def make_examples(frame: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for rule_id in rules["rule_id"]:
        group = "cognitive" if rule_id.startswith("C") else "social"
        subset = frame.loc[frame[f"{group}_rule_id"].eq(rule_id)].copy()
        if subset.empty:
            continue
        subset["_sample_hash"] = subset["source_record_id"].map(stable_hash)
        part = subset.sort_values("_sample_hash").head(5).drop(columns="_sample_hash")
        part.insert(0, "example_rule_id", rule_id)
        parts.append(part)
    if not parts:
        return pd.DataFrame()
    examples = pd.concat(parts, ignore_index=True)
    return examples[[
        "example_rule_id", "source_record_id", "job_title", "skill_cognitive", "skill_social",
        "cognitive_match_text", "cognitive_evidence", "social_match_text", "social_evidence",
    ]]


def main() -> int:
    storage = load_json(STORAGE_PATH)
    rules = load_rules()
    cognitive_matcher, cognitive_lookup = compile_group_matcher(rules, "cognitive")
    social_matcher, social_lookup = compile_group_matcher(rules, "social")

    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    output_root = Path(storage["features_root"]) / "non_ai_skills_pilot_v0.1"
    output_path = output_root / "jobs_2022_cognitive_social_v0.1.parquet"
    manifest_path = output_root / "manifest_2022.json"
    output_root.mkdir(parents=True, exist_ok=True)
    QC_ROOT.mkdir(parents=True, exist_ok=True)

    source = pq.read_table(
        cleaned_path,
        columns=["来源记录ID", "招聘岗位", "职位描述", "来源"],
    ).to_pandas()
    source = source.rename(columns={
        "来源记录ID": "source_record_id",
        "招聘岗位": "job_title",
        "职位描述": "job_description",
        "来源": "platform",
    })
    if len(source) != EXPECTED_SOURCE_ROWS or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗数据行数或主键异常")
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    source = source.loc[source["source_record_id"].isin(core_ids)].copy()
    if len(source) != len(core_ids) or source["source_record_id"].duplicated().any():
        raise RuntimeError("2022年清洗数据无法与confirmed_core_v2一一对应")

    prepared = source["job_description"].map(normalize_and_filter_text)
    source["skill_text"] = prepared.map(lambda item: item[0])
    source["skill_text_available"] = prepared.map(lambda item: item[1]).astype(bool)

    cognitive_results: list[dict] = []
    social_results: list[dict] = []
    for position, (text, available) in enumerate(
        zip(source["skill_text"], source["skill_text_available"]), start=1
    ):
        if available:
            cognitive_results.append(find_valid_match(text, cognitive_matcher, cognitive_lookup))
            social_results.append(find_valid_match(text, social_matcher, social_lookup))
        else:
            missing = {"value": None, "rule_id": "", "term_level": "", "match_text": "", "evidence": ""}
            cognitive_results.append(missing.copy())
            social_results.append(missing.copy())
        if position % 50_000 == 0:
            print(f"SKILL_PROGRESS={position}/{len(source)}", flush=True)

    cognitive = pd.DataFrame(cognitive_results)
    social = pd.DataFrame(social_results)
    source["skill_cognitive"] = pd.array(cognitive["value"], dtype="Int8")
    source["cognitive_rule_id"] = cognitive["rule_id"].astype("string")
    source["cognitive_term_level"] = cognitive["term_level"].astype("string")
    source["cognitive_match_text"] = cognitive["match_text"].astype("string")
    source["cognitive_evidence"] = cognitive["evidence"].astype("string")
    source["skill_social"] = pd.array(social["value"], dtype="Int8")
    source["social_rule_id"] = social["rule_id"].astype("string")
    source["social_term_level"] = social["term_level"].astype("string")
    source["social_match_text"] = social["match_text"].astype("string")
    source["social_evidence"] = social["evidence"].astype("string")
    source["non_ai_skill_version"] = VERSION

    feature_columns = [field.name for field in OUTPUT_SCHEMA]
    feature_frame = source[feature_columns].copy()
    table = pa.Table.from_pandas(feature_frame, schema=OUTPUT_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path, compression="zstd")

    total = len(source)
    available_count = int(source["skill_text_available"].sum())
    cognitive_count = int(source["skill_cognitive"].eq(1).sum())
    social_count = int(source["skill_social"].eq(1).sum())
    both_count = int((source["skill_cognitive"].eq(1) & source["skill_social"].eq(1)).sum())
    neither_count = int((source["skill_cognitive"].eq(0) & source["skill_social"].eq(0)).sum())
    summary = pd.DataFrame([
        {"metric": "total_records", "count": total, "share": 1.0},
        {"metric": "skill_text_available", "count": available_count, "share": available_count / total},
        {"metric": "skill_text_unavailable", "count": total - available_count, "share": (total - available_count) / total},
        {"metric": "skill_cognitive_1", "count": cognitive_count, "share": cognitive_count / total},
        {"metric": "skill_social_1", "count": social_count, "share": social_count / total},
        {"metric": "both_skills_1", "count": both_count, "share": both_count / total},
        {"metric": "neither_skill", "count": neither_count, "share": neither_count / total},
    ])
    write_csv(SUMMARY_PATH, summary)

    rule_counter = Counter(source["cognitive_rule_id"].loc[source["cognitive_rule_id"].ne("")])
    rule_counter.update(source["social_rule_id"].loc[source["social_rule_id"].ne("")])
    rule_counts = rules.copy()
    rule_counts["matched_records"] = rule_counts["rule_id"].map(rule_counter).fillna(0).astype(int)
    rule_counts["share_of_all_records"] = rule_counts["matched_records"] / total
    write_csv(RULE_COUNTS_PATH, rule_counts)

    platform = source.groupby("platform", dropna=False).agg(
        records=("source_record_id", "size"),
        text_available=("skill_text_available", "sum"),
        cognitive_positive=("skill_cognitive", lambda values: int(values.eq(1).sum())),
        social_positive=("skill_social", lambda values: int(values.eq(1).sum())),
    ).reset_index()
    platform["cognitive_rate"] = platform["cognitive_positive"] / platform["records"]
    platform["social_rate"] = platform["social_positive"] / platform["records"]
    write_csv(PLATFORM_PATH, platform)

    examples = make_examples(source, rules)
    write_csv(EXAMPLES_PATH, examples)
    review = choose_review_sample(source)
    if len(review) != REVIEW_TARGET or review["source_record_id"].duplicated().any():
        raise RuntimeError("人工复核样本数量或主键异常")
    write_csv(REVIEW_PATH, review)

    report = f"""# 2022年认知与社交技能变量试运行报告

结论：程序已按非AI技能v0.1规则完成2022年候选变量构建。结果仅用于诊断和人工复核，不能在人工验证前称为正式变量。

## 1. 样本和文本

- 回归底表记录：{total:,}条；
- 职位描述可用于判断：{available_count:,}条（{available_count / total:.2%}）；
- 文本不可判断：{total - available_count:,}条（{(total - available_count) / total:.2%}）。

## 2. 初步识别结果

- `skill_cognitive = 1`：{cognitive_count:,}条（{cognitive_count / total:.2%}）；
- `skill_social = 1`：{social_count:,}条（{social_count / total:.2%}）；
- 两类技能同时为1：{both_count:,}条（{both_count / total:.2%}）；
- 两类技能均为0：{neither_count:,}条（{neither_count / total:.2%}）。

以上比例反映词典规则的候选覆盖，不等于人工确认后的真实技能需求比例。

## 3. 当前规则

- 只使用含义完整的严格词和条件短语；
- 单独出现“分析、研究、沟通、团队、表达”等泛词不命中；
- 同一分句中存在“不要求、无需、无须、不必、不限”等否定表达时排除；
- 排除明显的公司介绍、福利、团队氛围和数据来源水印；
- 岗位名称只用于抽样，不直接决定技能变量。

## 4. 人工复核

已生成{len(review):,}条分层复核样本，覆盖认知单独命中、社交单独命中、两类同时命中、条件词命中、未命中的技术岗位和未命中的其他岗位。人工应只看原始招聘文本，分别标注认知和社交技能为1、0或9（无法判断）。

## 5. 输出

- 候选特征：`{output_path}`；
- 汇总：`{SUMMARY_PATH.relative_to(PROJECT_ROOT)}`；
- 规则命中：`{RULE_COUNTS_PATH.relative_to(PROJECT_ROOT)}`；
- 平台分布：`{PLATFORM_PATH.relative_to(PROJECT_ROOT)}`；
- 规则例子：`{EXAMPLES_PATH.relative_to(PROJECT_ROOT)}`；
- 人工复核样本：`{REVIEW_PATH.relative_to(PROJECT_ROOT)}`。

## 6. 下一步

1. 检查高频规则和典型切片；
2. 完成分层人工复核；
3. 计算查准率、漏判比例和标注一致率；
4. 根据预先确定的边界集中修订一次；
5. 再运行2018—2025年全样本并冻结正式版本。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")

    manifest = {
        "version": VERSION,
        "year": 2022,
        "source_path": str(cleaned_path),
        "core_path": str(core_path),
        "rule_path": str(RULE_PATH),
        "rule_sha256": sha256(RULE_PATH),
        "output_path": str(output_path),
        "output_rows": total,
        "review_rows": len(review),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"NON_AI_SKILL_2022_ROWS={total}")
    print(f"NON_AI_SKILL_2022_COGNITIVE={cognitive_count}")
    print(f"NON_AI_SKILL_2022_SOCIAL={social_count}")
    print(f"NON_AI_SKILL_2022_REVIEW={len(review)}")
    print("NON_AI_SKILL_2022=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
