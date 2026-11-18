"""验证V4.1全量职业特征表、人工反馈修复和版本一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from occupation_v04 import VERSION, build_classifier


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
VALIDATION_GOLD_PATH = PROJECT_ROOT / "config" / "occupation_independent_validation_v0.4.csv"
ANNUAL_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v041_all_years_annual.csv"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v041_validation_summary.csv"
REPORT_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v041_validation.md"
YEARS = range(2018, 2026)


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    base_rules = json.loads(BASE_RULE_PATH.read_text(encoding="utf-8"))
    valid_codes = set(base_rules["occupation_names"])
    annual = pd.read_csv(ANNUAL_PATH)
    checks: list[dict] = []

    for year in YEARS:
        v03_path = Path(storage["features_root"]) / "occupation_v0.3" / f"jobs_{year}_occupation_v0.3.parquet"
        v041_path = Path(storage["features_root"]) / "occupation_v0.4.1" / f"jobs_{year}_occupation_v0.4.1.parquet"
        expected = pq.ParquetFile(v03_path).metadata.num_rows
        table = pq.read_table(v041_path, columns=[
            "source_record_id", "occupation_l1", "occupation_id", "occupation_version",
        ]).to_pandas()
        rows = len(table)
        unique_ids = table["source_record_id"].astype(str).nunique(dropna=False)
        invalid_codes = int((~table["occupation_id"].astype(str).isin(valid_codes)).sum())
        l1_mismatch = int((
            table["occupation_l1"].astype(str)
            != table["occupation_id"].astype(str).str[0]
        ).sum())
        version_mismatch = int(table["occupation_version"].astype(str).ne(VERSION).sum())
        passed = (
            rows == expected == unique_ids
            and invalid_codes == 0
            and l1_mismatch == 0
            and version_mismatch == 0
        )
        checks.append({
            "year": year,
            "expected_rows": expected,
            "actual_rows": rows,
            "unique_ids": unique_ids,
            "invalid_codes": invalid_codes,
            "l1_mismatch": l1_mismatch,
            "version_mismatch": version_mismatch,
            "passed": passed,
        })

    check_frame = pd.DataFrame(checks)
    if not check_frame["passed"].all():
        raise RuntimeError(f"全量职业特征表校验失败：\n{check_frame.to_string(index=False)}")

    gold = pd.read_csv(VALIDATION_GOLD_PATH, dtype="string").fillna("")
    classifier = build_classifier()
    predictions = []
    for row in gold.itertuples(index=False):
        result = classifier.classify(row.job_title_raw, row.job_description_excerpt, "")
        predictions.append(result["occupation_id"])
    gold["v041_occupation_id"] = predictions
    before_code = int(gold["occupation_id_correct"].astype(int).sum())
    after_code = int(gold["v041_occupation_id"].eq(gold["manual_correct_occupation_id"]).sum())
    original_z99 = gold["v04_occupation_id"].eq("Z99")
    z99_resolved = int((
        original_z99
        & gold["manual_correct_occupation_id"].ne("Z99")
        & gold["v041_occupation_id"].eq(gold["manual_correct_occupation_id"])
    ).sum())
    known_correct_preserved = int((
        gold["occupation_id_correct"].eq("1")
        & gold["v041_occupation_id"].eq(gold["manual_correct_occupation_id"])
    ).sum())
    known_correct_total = int(gold["occupation_id_correct"].eq("1").sum())
    if after_code != len(gold) or known_correct_preserved != known_correct_total:
        raise RuntimeError("V4.1未完全解释300条人工反馈，或使原正确样本退化")

    check_frame.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    total = int(annual["records"].sum())
    classified = int(annual["classified"].sum())
    changed = int(annual["changed_from_v03"].sum())
    lines = [
        f"|{int(row.year)}|{int(row.actual_rows):,}|{int(row.unique_ids):,}|"
        f"{int(row.invalid_codes)}|{int(row.l1_mismatch)}|{int(row.version_mismatch)}|通过|"
        for row in check_frame.itertuples(index=False)
    ]
    REPORT_PATH.write_text(f"""# occupation V4.1 验证报告

## 结论

V4.1全量输出通过结构和口径校验，可作为当前阶段的职业类型候选变量。它没有覆盖清洗底表或V3文件。

## 全量检查

- 总记录：{total:,}条；
- 已分类：{classified:,}条，占{classified / total:.2%}；
- Z99：{total - classified:,}条，占{1 - classified / total:.2%}；
- 相比V3代码变化：{changed:,}条，占{changed / total:.2%}；
- 八个年度均满足：行数与V3一致、来源记录ID唯一、职业代码属于既定37类加Z99、一级代码与细类代码一致、版本号一致。

|年份|记录数|唯一ID|非法代码|一级代码不一致|版本不一致|结果|
|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(lines)}

## 人工反馈检查

- 300条独立验证在规则修订前，职业代码正确{before_code}条，准确率{before_code / len(gold):.2%}；
- V4.1吸收反馈后，300条代码与人工结果一致{after_code}条；
- 原V4的29条可判定Z99均被正确补入37类；
- 原先已正确的{known_correct_total}条职业代码全部保留，没有因新增规则发生退化。

修订后的300条一致率只能解释为“反馈修复检查”，不能再作为完全独立的模型准确率。修订前的90.33%才是这批独立样本对V4的外部检验结果。
""", encoding="utf-8")
    print(f"FULL_ROWS={total}")
    print(f"FULL_CLASSIFIED_SHARE={classified / total:.6f}")
    print(f"VALIDATION_BEFORE={before_code}/{len(gold)}")
    print(f"REMEDIATION_AFTER={after_code}/{len(gold)}")
    print("OCCUPATION_V041_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
