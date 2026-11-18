"""整理V4独立人工验证表，并输出可复现的验证结果。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "outputs"
    / "occupation_v04_validation_20261118"
    / "occupation_v04_独立验证样本_300条_已补标Z99_20261118.xlsx"
)
GOLD_PATH = PROJECT_ROOT / "config" / "occupation_independent_validation_v0.4.csv"
META_PATH = PROJECT_ROOT / "config" / "occupation_independent_validation_v0.4.meta.json"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v04_independent_validation_summary.csv"
ERROR_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v04_independent_validation_errors.csv"
REPORT_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v04_independent_validation_report.md"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_correct_standard_name(note: str) -> str:
    match = re.search(r"正确职业名称[：:]\s*([^。；;]+)", note or "")
    return match.group(1).strip() if match else ""


def clean_multiline_text(value: str) -> str:
    """保留换行，但删除每行末尾的空格，避免CSV产生无意义差异。"""
    return "\n".join(line.rstrip() for line in str(value).splitlines()).strip()


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    input_path = args.input.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    frame = pd.read_excel(input_path, sheet_name="独立验证样本", dtype="string").fillna("")
    required = [
        "序号", "年份", "验证分层", "来源记录ID", "原始岗位名称", "V4标准化岗位名称",
        "V4职业代码", "V4职业名称", "V4标准职业名称", "V4分类方法", "V4置信度",
        "职位描述节选", "人工判断", "正确职业代码", "错误原因", "人工备注", "复核状态",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"验证表缺少字段：{missing}")
    if len(frame) != 300 or frame["来源记录ID"].duplicated().any():
        raise RuntimeError("验证表必须包含300条不重复的来源记录ID")

    for column in required:
        frame[column] = frame[column].map(clean_multiline_text)
    if not frame["人工判断"].isin(["正确", "错误", "无法判断"]).all():
        bad = frame.loc[~frame["人工判断"].isin(["正确", "错误", "无法判断"]), "人工判断"].unique()
        raise RuntimeError(f"人工判断存在非标准值：{bad.tolist()}")
    if frame["正确职业代码"].eq("").any() or frame["复核状态"].ne("已完成").any():
        raise RuntimeError("验证表仍有未完成记录或空白正确职业代码")

    rules = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    valid_codes = set(rules["occupation_names"])
    invalid_codes = sorted(set(frame["正确职业代码"]) - valid_codes)
    if invalid_codes:
        raise RuntimeError(f"正确职业代码超出37类口径：{invalid_codes}")

    gold = pd.DataFrame({
        "sequence": frame["序号"].astype(int),
        "year": frame["年份"].astype(int),
        "validation_stratum": frame["验证分层"],
        "source_record_id": frame["来源记录ID"],
        "job_title_raw": frame["原始岗位名称"],
        "job_title_normalized_v04": frame["V4标准化岗位名称"],
        "job_description_excerpt": frame["职位描述节选"],
        "v04_occupation_id": frame["V4职业代码"],
        "v04_occupation_name": frame["V4职业名称"],
        "v04_standard_name": frame["V4标准职业名称"],
        "v04_method": frame["V4分类方法"],
        "v04_confidence": frame["V4置信度"],
        "manual_stage1_judgment": frame["人工判断"],
        "manual_correct_occupation_id": frame["正确职业代码"],
        "manual_error_reason": frame["错误原因"],
        "manual_note": frame["人工备注"],
    })
    gold["manual_correct_standard_name"] = frame["人工备注"].map(extract_correct_standard_name)
    gold["stage1_correct"] = gold["manual_stage1_judgment"].eq("正确").astype(int)
    gold["occupation_id_correct"] = gold["v04_occupation_id"].eq(gold["manual_correct_occupation_id"]).astype(int)
    GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    gold.to_csv(GOLD_PATH, index=False, encoding="utf-8-sig")

    summary_rows = []
    for method, group in [("总体", gold), *list(gold.groupby("v04_method", sort=True))]:
        stage1_count = int(group["stage1_correct"].sum())
        code_count = int(group["occupation_id_correct"].sum())
        summary_rows.append({
            "分类方法": method,
            "样本数": len(group),
            "第一环节正确数": stage1_count,
            "第一环节准确率": rate(stage1_count, len(group)),
            "职业代码正确数": code_count,
            "职业代码准确率": rate(code_count, len(group)),
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    errors = gold.loc[(gold["stage1_correct"].eq(0)) | (gold["occupation_id_correct"].eq(0))].copy()
    errors.to_csv(ERROR_PATH, index=False, encoding="utf-8-sig")

    stage1_correct = int(gold["stage1_correct"].sum())
    code_correct = int(gold["occupation_id_correct"].sum())
    classified = gold.loc[gold["v04_occupation_id"].ne("Z99")]
    classified_stage1 = int(classified["stage1_correct"].sum())
    classified_code = int(classified["occupation_id_correct"].sum())
    z99 = gold.loc[gold["v04_occupation_id"].eq("Z99")]
    z99_resolved = int(z99["manual_correct_occupation_id"].ne("Z99").sum())

    REPORT_PATH.write_text(
        f"""# occupation V4 独立人工验证结果

## 总体结果

- 样本数：{len(gold)}条；
- 第一环节（标准职业名称）正确：{stage1_correct}条，准确率{rate(stage1_correct, len(gold)):.2%}；
- 第二环节（37类职业代码）正确：{code_correct}条，准确率{rate(code_correct, len(gold)):.2%}。

## 分开看已有分类与Z99

- V4已分类样本：{len(classified)}条；第一环节正确{classified_stage1}条（{rate(classified_stage1, len(classified)):.2%}），职业代码正确{classified_code}条（{rate(classified_code, len(classified)):.2%}）；
- V4原Z99样本：{len(z99)}条，其中{z99_resolved}条经人工判断可归入37类，{len(z99) - z99_resolved}条继续保留Z99。

## 解释

V4当前最主要的问题是未分类覆盖不足，而不是已经分类样本的大类代码大量错分。修订时应优先补充可复用别名和上下文规则。宽泛岗位名称仍需结合职位描述，不能只按标题强行分类。
""",
        encoding="utf-8",
    )
    META_PATH.write_text(json.dumps({
        "source_workbook": str(input_path),
        "source_sha256": sha256(input_path),
        "records": len(gold),
        "stage1_correct": stage1_correct,
        "occupation_id_correct": code_correct,
        "z99_resolved": z99_resolved,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"VALIDATION_RECORDS={len(gold)}")
    print(f"STAGE1_ACCURACY={rate(stage1_correct, len(gold)):.6f}")
    print(f"OCCUPATION_ID_ACCURACY={rate(code_correct, len(gold)):.6f}")
    print(f"Z99_RESOLVED={z99_resolved}/{len(z99)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
