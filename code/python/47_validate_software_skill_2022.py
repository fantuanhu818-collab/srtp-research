"""独立验证2022年软件技能候选变量的结构、主键和证据可追溯性。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "software_skill_rules_v0.1.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
VERSION = "software_skill_v0.1_20261119"
EXPECTED_ROWS = 328_548

SUMMARY_PATH = QC_ROOT / "software_skill_v01_2022_summary.csv"
REVIEW_PATH = QC_ROOT / "software_skill_v01_2022_review_sample.csv"
OCCUPATION_PATH = QC_ROOT / "software_skill_v01_2022_occupation_distribution.csv"
VALIDATION_PATH = QC_ROOT / "software_skill_v01_2022_validation.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_ids(value: object) -> list[str]:
    if value is None or pd.isna(value) or not str(value):
        return []
    return [item for item in str(value).split("|") if item]


def main() -> int:
    storage = load_json(STORAGE_PATH)
    feature_root = Path(storage["features_root"]) / "software_skill_pilot_v0.1"
    evidence_root = Path(storage["evidence_root"]) / "software_skill_pilot_v0.1"
    output_path = feature_root / "jobs_2022_software_skill_v0.1.parquet"
    evidence_path = evidence_root / "software_skill_hits_2022_v0.1.parquet"
    manifest_path = feature_root / "manifest_2022.json"
    core_path = (
        Path(storage["features_root"])
        / "confirmed_core_v2"
        / "jobs_2022_confirmed_core.parquet"
    )

    required_paths = [
        output_path,
        evidence_path,
        manifest_path,
        core_path,
        RULE_PATH,
        SUMMARY_PATH,
        REVIEW_PATH,
        OCCUPATION_PATH,
    ]
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(path)

    frame = pq.read_table(output_path).to_pandas()
    evidence = pq.read_table(evidence_path).to_pandas()
    core_ids = set(
        pq.read_table(core_path, columns=["source_record_id"])["source_record_id"].to_pylist()
    )
    rules = pd.read_csv(RULE_PATH, dtype="string").fillna("")
    valid_rule_ids = set(rules["rule_id"])
    summary = pd.read_csv(SUMMARY_PATH)
    review = pd.read_csv(REVIEW_PATH, dtype="string").fillna("")
    occupation = pd.read_csv(OCCUPATION_PATH)
    manifest = load_json(manifest_path)

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append((name, bool(condition), detail))

    check("输出行数正确", len(frame) == EXPECTED_ROWS, f"输出{len(frame):,}条")
    check(
        "输出主键唯一",
        not frame["source_record_id"].duplicated().any(),
        f"重复{int(frame['source_record_id'].duplicated().sum()):,}条",
    )
    output_ids = set(frame["source_record_id"])
    check(
        "输出ID与核心底表一致",
        output_ids == core_ids,
        f"对称差{len(output_ids.symmetric_difference(core_ids)):,}条",
    )

    allowed = {0, 1}
    observed = set(frame["skill_software"].dropna().astype(int).unique())
    check("软件变量取值合法", observed.issubset(allowed), f"取值{sorted(observed)}")
    unavailable = ~frame["skill_text_available"]
    available = frame["skill_text_available"]
    check(
        "不可用文本保持缺失",
        frame.loc[unavailable, "skill_software"].isna().all(),
        f"不可用文本{int(unavailable.sum()):,}条",
    )
    check(
        "可用文本均编码0或1",
        frame.loc[available, "skill_software"].notna().all(),
        f"可用文本{int(available.sum()):,}条",
    )

    positive = frame["skill_software"].eq(1)
    negative = frame["skill_software"].eq(0)
    check(
        "阳性记录保留规则和证据",
        frame.loc[positive, ["software_rule_ids", "software_evidence"]].ne("").all().all(),
        f"阳性{int(positive.sum()):,}条",
    )
    check(
        "阴性记录没有命中规则",
        frame.loc[negative, "software_rule_ids"].fillna("").eq("").all()
        and frame.loc[negative, "software_hit_count"].eq(0).all(),
        f"阴性{int(negative.sum()):,}条",
    )

    listed_rule_ids = {
        rule_id for value in frame["software_rule_ids"] for rule_id in split_ids(value)
    }
    check(
        "输出规则ID均在词典中",
        listed_rule_ids.issubset(valid_rule_ids),
        f"未知规则{sorted(listed_rule_ids - valid_rule_ids)}",
    )
    evidence_rule_ids = set(evidence["rule_id"])
    check(
        "证据规则ID均在词典中",
        evidence_rule_ids.issubset(valid_rule_ids),
        f"证据使用{len(evidence_rule_ids)}条规则",
    )
    check(
        "稀疏证据主键规则不重复",
        not evidence.duplicated(["source_record_id", "rule_id"]).any(),
        f"重复{int(evidence.duplicated(['source_record_id', 'rule_id']).sum()):,}条",
    )
    check(
        "稀疏证据来自输出",
        set(evidence["source_record_id"]).issubset(output_ids),
        f"证据{len(evidence):,}条",
    )

    expected_hit_counts = frame["software_rule_ids"].map(lambda value: len(split_ids(value)))
    check(
        "逐条命中数量一致",
        expected_hit_counts.eq(frame["software_hit_count"]).all(),
        f"不一致{int((expected_hit_counts != frame['software_hit_count']).sum()):,}条",
    )
    combined_subgroup = frame["software_office_basic"].eq(1) | frame["software_professional"].eq(1)
    check(
        "主变量与办公专业子类一致",
        combined_subgroup.eq(positive).all(),
        f"不一致{int((combined_subgroup != positive).sum()):,}条",
    )
    check(
        "标题命中只出现在阳性记录",
        (~frame["software_title_hit"].eq(1) | positive).all(),
        f"标题命中{int(frame['software_title_hit'].eq(1).sum()):,}条",
    )
    check(
        "规则版本唯一且正确",
        set(frame["software_rule_version"].unique()) == {VERSION},
        f"版本{sorted(frame['software_rule_version'].unique())}",
    )

    summary_map = dict(zip(summary["metric"], summary["count"]))
    expected_summary = {
        "total_records": len(frame),
        "skill_text_available": int(available.sum()),
        "skill_text_unavailable": int(unavailable.sum()),
        "skill_software_1": int(positive.sum()),
        "software_office_basic_1": int(frame["software_office_basic"].eq(1).sum()),
        "software_professional_1": int(frame["software_professional"].eq(1).sum()),
    }
    summary_ok = all(int(summary_map.get(key, -1)) == value for key, value in expected_summary.items())
    check("汇总与逐条输出一致", summary_ok, f"核对{len(expected_summary)}项指标")

    check(
        "复核样本数量和主键正确",
        len(review) == 240 and not review["source_record_id"].duplicated().any(),
        f"复核样本{len(review)}条",
    )
    check(
        "复核样本来自输出",
        set(review["source_record_id"]).issubset(output_ids),
        f"样本ID差异{len(set(review['source_record_id']) - output_ids)}条",
    )
    check(
        "职业分布记录数守恒",
        int(occupation["records"].sum()) == EXPECTED_ROWS,
        f"职业分布合计{int(occupation['records'].sum()):,}条",
    )
    check(
        "清单记录规则哈希正确",
        manifest.get("rule_sha256") == sha256(RULE_PATH),
        f"清单哈希{manifest.get('rule_sha256', '')}",
    )
    check(
        "清单记录输出行数正确",
        int(manifest.get("output_rows", -1)) == EXPECTED_ROWS,
        f"清单行数{manifest.get('output_rows')}",
    )

    passed = all(result for _, result, _ in checks)
    lines = [
        "# 2022年软件技能候选变量独立验证",
        "",
        f"结论：{'通过' if passed else '未通过'}。本验证只确认程序结构和可追溯性，不能替代人工准确性复核。",
        "",
        "|检查项|结果|说明|",
        "|---|---|---|",
    ]
    for name, result, detail in checks:
        lines.append(f"|{name}|{'PASS' if result else 'FAIL'}|{detail}|")
    lines.extend(
        [
            "",
            "## 限制",
            "",
            "- 当前结果是词典规则产生的候选变量；",
            "- 软件技能真实查准率、漏判比例和标注一致率必须通过人工复核计算；",
            "- 基础办公软件按照项目组口径进入主变量，但必须单独报告其占比；",
            "- 人工复核和规则修订完成前不得并入正式冻结的基准回归数据。",
            "",
        ]
    )
    VALIDATION_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"SOFTWARE_SKILL_VALIDATION_CHECKS={len(checks)}")
    print(f"SOFTWARE_SKILL_2022_VALIDATION={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
