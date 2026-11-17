"""独立验证2022年认知技能和社交技能候选变量。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "non_ai_skill_rules_v0.1.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "non_ai_skill_v01_2022_summary.csv"
REVIEW_PATH = QC_ROOT / "non_ai_skill_v01_2022_review_sample.csv"
VALIDATION_PATH = QC_ROOT / "non_ai_skill_v01_2022_validation.md"
EXPECTED_REVIEW_ROWS = 240


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    storage = load_json(STORAGE_PATH)
    cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / "jobs_2022_cleaned.parquet"
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    output_path = (
        Path(storage["features_root"])
        / "non_ai_skills_pilot_v0.1"
        / "jobs_2022_cognitive_social_v0.1.parquet"
    )

    required_paths = [cleaned_path, core_path, output_path, RULE_PATH, SUMMARY_PATH, REVIEW_PATH]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise RuntimeError(f"缺少验证所需文件：{missing}")

    source_ids = set(pq.read_table(cleaned_path, columns=["来源记录ID"])["来源记录ID"].to_pylist())
    core_ids = set(pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist())
    output = pq.read_table(output_path).to_pandas()
    output_ids = set(output["source_record_id"])
    rules = pd.read_csv(RULE_PATH, dtype="string").fillna("")
    review = pd.read_csv(REVIEW_PATH, dtype="string").fillna("")
    summary = pd.read_csv(SUMMARY_PATH)

    checks: list[tuple[str, bool, str]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append((name, bool(passed), detail))

    add("输出主键唯一", not output["source_record_id"].duplicated().any(), f"输出{len(output):,}条")
    add("输出与核心底表行数一致", len(output) == len(core_ids), f"核心底表{len(core_ids):,}条")
    add("输出ID与核心底表一致", output_ids == core_ids, f"差异{len(output_ids ^ core_ids):,}条")
    add("核心底表是清洗数据子集", core_ids.issubset(source_ids), f"清洗数据{len(source_ids):,}条")

    cognitive_domain = set(output["skill_cognitive"].dropna().astype(int).unique())
    social_domain = set(output["skill_social"].dropna().astype(int).unique())
    add("认知变量取值合法", cognitive_domain.issubset({0, 1}), f"取值{sorted(cognitive_domain)}")
    add("社交变量取值合法", social_domain.issubset({0, 1}), f"取值{sorted(social_domain)}")

    unavailable = ~output["skill_text_available"]
    available = output["skill_text_available"]
    add(
        "不可用文本保持缺失",
        output.loc[unavailable, ["skill_cognitive", "skill_social"]].isna().all().all(),
        f"不可用文本{int(unavailable.sum()):,}条",
    )
    add(
        "可用文本均编码0或1",
        output.loc[available, ["skill_cognitive", "skill_social"]].notna().all().all(),
        f"可用文本{int(available.sum()):,}条",
    )

    cognitive_positive = output["skill_cognitive"].eq(1)
    social_positive = output["skill_social"].eq(1)
    add(
        "认知命中保留证据",
        output.loc[cognitive_positive, ["cognitive_rule_id", "cognitive_match_text", "cognitive_evidence"]]
        .fillna("").ne("").all().all(),
        f"认知命中{int(cognitive_positive.sum()):,}条",
    )
    add(
        "社交命中保留证据",
        output.loc[social_positive, ["social_rule_id", "social_match_text", "social_evidence"]]
        .fillna("").ne("").all().all(),
        f"社交命中{int(social_positive.sum()):,}条",
    )

    cognitive_rule_ids = set(rules.loc[rules["skill_group"].eq("cognitive"), "rule_id"])
    social_rule_ids = set(rules.loc[rules["skill_group"].eq("social"), "rule_id"])
    output_cognitive_rules = set(output.loc[cognitive_positive, "cognitive_rule_id"].dropna())
    output_social_rules = set(output.loc[social_positive, "social_rule_id"].dropna())
    add(
        "认知规则ID可追溯",
        output_cognitive_rules.issubset(cognitive_rule_ids),
        f"使用{len(output_cognitive_rules)}条规则",
    )
    add(
        "社交规则ID可追溯",
        output_social_rules.issubset(social_rule_ids),
        f"使用{len(output_social_rules)}条规则",
    )

    add("复核样本数量正确", len(review) == EXPECTED_REVIEW_ROWS, f"复核样本{len(review):,}条")
    add("复核样本主键唯一", not review["source_record_id"].duplicated().any(), "不重复抽样")
    add(
        "复核样本来自输出",
        set(review["source_record_id"]).issubset(output_ids),
        f"样本ID差异{len(set(review['source_record_id']) - output_ids):,}条",
    )

    summary_lookup = dict(zip(summary["metric"], summary["count"]))
    expected_summary = {
        "total_records": len(output),
        "skill_text_available": int(available.sum()),
        "skill_text_unavailable": int(unavailable.sum()),
        "skill_cognitive_1": int(cognitive_positive.sum()),
        "skill_social_1": int(social_positive.sum()),
        "both_skills_1": int((cognitive_positive & social_positive).sum()),
        "neither_skill": int((output["skill_cognitive"].eq(0) & output["skill_social"].eq(0)).sum()),
    }
    summary_ok = all(int(summary_lookup.get(key, -1)) == value for key, value in expected_summary.items())
    add("汇总与逐条输出一致", summary_ok, f"核对{len(expected_summary)}项指标")

    failed = [name for name, passed, _ in checks if not passed]
    lines = [
        "# 2022年认知与社交技能候选变量独立验证",
        "",
        f"结论：{'通过' if not failed else '未通过'}。本验证只确认程序结构和可追溯性，不能替代人工准确性复核。",
        "",
        "|检查项|结果|说明|",
        "|---|---|---|",
    ]
    for name, passed, detail in checks:
        lines.append(f"|{name}|{'PASS' if passed else 'FAIL'}|{detail}|")
    lines.extend([
        "",
        "## 限制",
        "",
        "- 当前结果是词典规则产生的候选变量；",
        "- 查准率、漏判比例和标注一致率必须在人工复核后计算；",
        "- 人工复核和规则修订完成前不得并入正式冻结的基准回归数据。",
        "",
    ])
    VALIDATION_PATH.write_text("\n".join(lines), encoding="utf-8")

    if failed:
        raise RuntimeError(f"验证失败：{failed}")
    print(f"NON_AI_SKILL_VALIDATION_CHECKS={len(checks)}")
    print("NON_AI_SKILL_2022_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
