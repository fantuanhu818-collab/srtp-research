"""准备2022年三类非AI技能的统一人工复核样本。

目标是把软件、认知、社交技能放在同一批240条广告上复核，同时保持人工判断
与程序结果相互隔离。脚本只生成CSV、清单和校验报告，不修改任何候选特征数据。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
VERSION = "non_ai_skill_unified_review_2022_v0.1_20261119"
SAMPLE_SIZE = 240
PER_STRATUM = 40

OUTPUT_CSV = QC_ROOT / "non_ai_skill_unified_review_2022_v0.1.csv"
DATA_JSON_PATH = QC_ROOT / "non_ai_skill_unified_review_2022_v0.1.json"
MANIFEST_PATH = QC_ROOT / "non_ai_skill_unified_review_2022_v0.1_manifest.json"
VALIDATION_PATH = QC_ROOT / "non_ai_skill_unified_review_2022_v0.1_validation.md"

TECHNICAL_TITLE_PATTERN = re.compile(
    r"工程师|开发|技术|分析|研究|算法|数据|设计|产品|项目|测试|运维|实施|程序|软件|数据库|网络|架构|系统",
    flags=re.IGNORECASE,
)

STRATA = [
    ("professional_software", "专业软件技能"),
    ("office_software", "办公软件技能"),
    ("conditional_or_overlap", "条件词或多技能重叠"),
    ("cognitive_positive", "认知技能命中"),
    ("social_positive", "社交技能命中"),
    ("all_negative", "三类均未命中"),
]


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def choose(frame: pd.DataFrame, condition: pd.Series, number: int, salt: str) -> pd.DataFrame:
    candidates = frame.loc[condition].copy()
    candidates["_selection_hash"] = candidates["source_record_id"].map(
        lambda value: stable_hash(f"{value}|{salt}")
    )
    return candidates.sort_values("_selection_hash").head(number).drop(columns="_selection_hash")


def main() -> None:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    features_root = Path(storage["features_root"])
    curated_root = Path(storage["curated_root"])

    software_path = (
        features_root
        / "software_skill_pilot_v0.1"
        / "jobs_2022_software_skill_v0.1.parquet"
    )
    cognitive_social_path = (
        features_root
        / "non_ai_skills_pilot_v0.1"
        / "jobs_2022_cognitive_social_v0.1.parquet"
    )
    cleaned_path = curated_root / "cleaned_v1" / "jobs_2022_cleaned.parquet"

    software_columns = [
        "source_record_id", "skill_software", "skill_text_available",
        "software_rule_ids", "software_subgroups", "software_term_levels",
        "software_match_text", "software_evidence", "software_office_basic",
        "software_professional", "software_has_conditional", "software_title_hit",
    ]
    cognitive_social_columns = [
        "source_record_id", "skill_cognitive", "skill_social", "skill_text_available",
        "cognitive_rule_id", "cognitive_term_level", "cognitive_match_text",
        "cognitive_evidence", "social_rule_id", "social_term_level",
        "social_match_text", "social_evidence",
    ]

    software = pd.read_parquet(software_path, columns=software_columns).rename(
        columns={"skill_text_available": "software_text_available"}
    )
    cognitive_social = pd.read_parquet(
        cognitive_social_path, columns=cognitive_social_columns
    ).rename(columns={"skill_text_available": "cognitive_social_text_available"})
    source = pd.read_parquet(
        cleaned_path,
        columns=["来源记录ID", "招聘岗位", "职位描述", "来源"],
    ).rename(
        columns={
            "来源记录ID": "source_record_id",
            "招聘岗位": "job_title",
            "职位描述": "job_description",
            "来源": "platform",
        }
    )

    for name, data in [
        ("software", software),
        ("cognitive_social", cognitive_social),
        ("source", source),
    ]:
        if data["source_record_id"].duplicated().any():
            raise ValueError(f"{name}存在重复source_record_id，不能进行一对一合并")

    frame = source.merge(software, on="source_record_id", how="inner", validate="one_to_one")
    frame = frame.merge(
        cognitive_social, on="source_record_id", how="inner", validate="one_to_one"
    )
    if len(frame) != len(source):
        raise ValueError(f"合并后行数{len(frame):,}与源数据{len(source):,}不一致")
    frame["job_title"] = frame["job_title"].fillna("").astype(str)
    frame["job_description"] = frame["job_description"].fillna("").astype(str)
    frame["platform"] = frame["platform"].fillna("").astype(str)
    frame["review_text_available"] = (
        frame["software_text_available"] | frame["cognitive_social_text_available"]
    )
    availability_difference = int(
        frame["software_text_available"].ne(frame["cognitive_social_text_available"]).sum()
    )
    available = frame.loc[frame["review_text_available"]].copy()
    available["positive_skill_count"] = available[
        ["skill_software", "skill_cognitive", "skill_social"]
    ].sum(axis=1)

    selected_parts: list[pd.DataFrame] = []
    used: set[str] = set()

    def add_stratum(code: str, label: str, condition: pd.Series, number: int = PER_STRATUM) -> None:
        eligible = condition & ~available["source_record_id"].isin(used)
        part = choose(available, eligible, number, f"review-v0.1|{code}")
        if len(part) != number:
            raise ValueError(f"{label}只有{len(part)}条可抽样，少于目标{number}条")
        part.insert(0, "review_stratum_code", code)
        part.insert(1, "review_stratum", label)
        selected_parts.append(part)
        used.update(part["source_record_id"].tolist())

    add_stratum(
        "professional_software",
        "专业软件技能",
        available["skill_software"].eq(1)
        & available["software_professional"].eq(1)
        & available["software_office_basic"].eq(0),
    )
    add_stratum(
        "office_software",
        "办公软件技能",
        available["skill_software"].eq(1)
        & available["software_office_basic"].eq(1)
        & available["software_professional"].eq(0),
    )
    add_stratum(
        "conditional_or_overlap",
        "条件词或多技能重叠",
        available["software_has_conditional"].eq(1)
        | available["positive_skill_count"].ge(2),
    )
    add_stratum(
        "cognitive_positive",
        "认知技能命中",
        available["skill_cognitive"].eq(1),
    )
    add_stratum(
        "social_positive",
        "社交技能命中",
        available["skill_social"].eq(1),
    )

    negative = (
        available["skill_software"].eq(0)
        & available["skill_cognitive"].eq(0)
        & available["skill_social"].eq(0)
        & ~available["source_record_id"].isin(used)
    )
    technical = available["job_title"].str.contains(TECHNICAL_TITLE_PATTERN, na=False)
    negative_technical = choose(
        available, negative & technical, 20, "review-v0.1|all-negative|technical"
    )
    negative_other = choose(
        available, negative & ~technical, 20, "review-v0.1|all-negative|other"
    )
    negative_part = pd.concat([negative_technical, negative_other], ignore_index=True)
    if len(negative_part) != PER_STRATUM:
        raise ValueError("三类均未命中层无法组成20条技术岗位和20条其他岗位")
    negative_part.insert(0, "review_stratum_code", "all_negative")
    negative_part.insert(1, "review_stratum", "三类均未命中")
    selected_parts.append(negative_part)

    sample = pd.concat(selected_parts, ignore_index=True)
    if len(sample) != SAMPLE_SIZE or sample["source_record_id"].duplicated().any():
        raise ValueError("统一复核样本不是240条互不重复记录")

    assigned_parts: list[pd.DataFrame] = []
    for code, _label in STRATA:
        part = sample.loc[sample["review_stratum_code"].eq(code)].copy()
        part["_assignment_hash"] = part["source_record_id"].map(
            lambda value: stable_hash(f"{value}|review-v0.1|assignment")
        )
        part = part.sort_values("_assignment_hash").drop(columns="_assignment_hash")
        part["review_mode"] = ["双人独立复核"] * 10 + ["仅A复核"] * 15 + ["仅B复核"] * 15
        part["assigned_reviewer"] = ["A+B"] * 10 + ["A"] * 15 + ["B"] * 15
        assigned_parts.append(part)

    sample = pd.concat(assigned_parts, ignore_index=True)
    sample["_display_hash"] = sample["source_record_id"].map(
        lambda value: stable_hash(f"{value}|review-v0.1|display-order")
    )
    sample = sample.sort_values("_display_hash").drop(columns="_display_hash").reset_index(drop=True)
    sample.insert(0, "sample_no", range(1, SAMPLE_SIZE + 1))

    for column in [
        "A_software", "A_cognitive", "A_social", "A_notes",
        "B_software", "B_cognitive", "B_social", "B_notes",
        "final_software", "final_cognitive", "final_social", "adjudication_notes",
    ]:
        sample[column] = ""

    output_columns = [
        "sample_no", "source_record_id", "platform", "job_title", "job_description",
        "review_mode", "assigned_reviewer", "review_stratum_code", "review_stratum",
        "skill_software", "software_office_basic", "software_professional",
        "software_has_conditional", "software_title_hit", "software_rule_ids",
        "software_subgroups", "software_term_levels", "software_match_text",
        "software_evidence", "skill_cognitive", "cognitive_rule_id",
        "cognitive_term_level", "cognitive_match_text", "cognitive_evidence",
        "skill_social", "social_rule_id", "social_term_level", "social_match_text",
        "social_evidence", "A_software", "A_cognitive", "A_social", "A_notes",
        "B_software", "B_cognitive", "B_social", "B_notes", "final_software",
        "final_cognitive", "final_social", "adjudication_notes",
    ]
    output = sample[output_columns].copy()
    write_csv(OUTPUT_CSV, output)
    DATA_JSON_PATH.write_text(
        json.dumps(output.to_dict(orient="records"), ensure_ascii=False), encoding="utf-8"
    )

    stratum_counts = output["review_stratum"].value_counts().sort_index().to_dict()
    assignment_counts = output["assigned_reviewer"].value_counts().sort_index().to_dict()
    manifest = {
        "version": VERSION,
        "created_for": "2022年软件、认知、社交三类非AI技能统一人工复核",
        "sample_size": len(output),
        "unique_source_record_ids": int(output["source_record_id"].nunique()),
        "stratum_counts": {str(key): int(value) for key, value in stratum_counts.items()},
        "assignment_counts": {str(key): int(value) for key, value in assignment_counts.items()},
        "reviewer_required_rows": {"A": 150, "B": 150},
        "double_coded_rows": 60,
        "sampling_notes": [
            "每层40条：10条双人独立复核、15条仅A复核、15条仅B复核。",
            "三类均未命中层由20条技术岗位和20条其他岗位组成。",
            "显示顺序经稳定哈希打散，人工复核表不展示程序结果与抽样层。",
            (
                f"两套候选特征有{availability_difference}条文本可用标记不同；统一复核采用"
                "岗位名称或职位描述任一可用即纳入的并集口径。"
            ),
        ],
        "inputs": {
            "software_candidate": {"path": str(software_path), "sha256": sha256(software_path)},
            "cognitive_social_candidate": {
                "path": str(cognitive_social_path),
                "sha256": sha256(cognitive_social_path),
            },
            "cleaned_source": {"path": str(cleaned_path), "sha256": sha256(cleaned_path)},
        },
        "outputs": {
            "csv": {"path": str(OUTPUT_CSV), "sha256": sha256(OUTPUT_CSV)},
            "json_for_workbook": {
                "path": str(DATA_JSON_PATH),
                "sha256": sha256(DATA_JSON_PATH),
            },
        },
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checks = {
        "样本共240条": len(output) == 240,
        "来源记录ID不重复": output["source_record_id"].nunique() == 240,
        "六个抽样层各40条": set(stratum_counts.values()) == {40} and len(stratum_counts) == 6,
        "双人独立复核共60条": int((output["assigned_reviewer"] == "A+B").sum()) == 60,
        "仅A复核共90条": int((output["assigned_reviewer"] == "A").sum()) == 90,
        "仅B复核共90条": int((output["assigned_reviewer"] == "B").sum()) == 90,
        "A需复核150条": int(output["assigned_reviewer"].isin(["A", "A+B"]).sum()) == 150,
        "B需复核150条": int(output["assigned_reviewer"].isin(["B", "A+B"]).sum()) == 150,
        "人工判定列保持空白": output[
            ["A_software", "A_cognitive", "A_social", "B_software", "B_cognitive", "B_social"]
        ].replace("", pd.NA).isna().all().all(),
    }
    lines = [
        "# 2022年三类非AI技能统一人工复核样本校验",
        "",
        f"- 版本：`{VERSION}`",
        f"- 样本文件：`{OUTPUT_CSV}`",
        "",
        "## 自动校验",
        "",
    ]
    lines.extend(f"- {'通过' if passed else '失败'}：{name}" for name, passed in checks.items())
    lines.extend(["", "## 分层数量", ""])
    lines.extend(f"- {name}：{count}条" for name, count in stratum_counts.items())
    lines.extend(["", "## 分工数量", ""])
    lines.extend(f"- {name}：{count}条" for name, count in assignment_counts.items())
    VALIDATION_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"自动校验失败：{failed}")

    print(f"已生成统一复核样本：{OUTPUT_CSV}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
