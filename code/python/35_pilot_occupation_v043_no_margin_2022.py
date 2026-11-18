"""取消分差门槛，在2022年生成V4.3无分差实验版和独立复核样本。"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
EVIDENCE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_evidence_rules_v0.4.2.json"
EXPERIMENT_PATH = PROJECT_ROOT / "config" / "occupation_v0.4.3_no_margin_experiment.json"
AUDIT_PATH = (
    PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118"
    / "occupation_v042_2022_z99_evidence_audit.csv"
)
ANNOTATED_PATH = (
    PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118"
    / "occupation_v042_2022_人工复核样本_400条_已标注.xlsx"
)
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "occupation_v043_no_margin_20261118"
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
SAMPLE_SIZE = 300
RANDOM_SEED = 20261118


def normalize(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return re.sub(r"\s+", "", text)


def actual_matches(patterns: list[str], text: str) -> list[str]:
    matches: list[str] = []
    for raw in patterns:
        match = re.search(raw, text, flags=re.IGNORECASE)
        if match is not None and match.group(0) not in matches:
            matches.append(match.group(0))
    return matches


def load_annotated_ids() -> set[str]:
    workbook = load_workbook(ANNOTATED_PATH, read_only=True, data_only=True)
    sheet = workbook["人工复核"]
    return {
        str(row[1]).strip()
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row[0] is not None and row[1] is not None
    }


def margin_band(value: float) -> str:
    if value < 0.5:
        return "分差0"
    if value < 1.5:
        return "分差约1"
    return "分差1—2之间"


def stratified_sample(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    frame = frame.copy()
    frame["抽样分层"] = frame.apply(
        lambda row: f"{row['candidate_occupation_id']}｜{margin_band(float(row['score_margin']))}",
        axis=1,
    )
    sizes = frame.groupby("抽样分层").size().sort_index()
    if n >= len(frame):
        result = frame.copy()
        result["分层总数"] = result["抽样分层"].map(sizes)
        result["抽样权重"] = 1.0
        return result

    allocation = pd.Series(1, index=sizes.index, dtype=int)
    remaining = n - int(allocation.sum())
    capacity = sizes - allocation
    if remaining < 0:
        allocation[:] = 0
        for key in sizes.sort_values(ascending=False).head(n).index:
            allocation.loc[key] = 1
    elif remaining > 0 and int(capacity.sum()) > 0:
        raw_extra = capacity / capacity.sum() * remaining
        extra = raw_extra.apply(math.floor).astype(int)
        allocation += extra
        residual = n - int(allocation.sum())
        order = (raw_extra - extra).sort_values(ascending=False).index.tolist()
        for key in order:
            if residual <= 0:
                break
            if allocation.loc[key] < sizes.loc[key]:
                allocation.loc[key] += 1
                residual -= 1

    pieces: list[pd.DataFrame] = []
    for index, (key, group) in enumerate(frame.groupby("抽样分层", sort=True)):
        take = min(int(allocation.loc[key]), len(group))
        if take:
            pieces.append(group.sample(n=take, random_state=RANDOM_SEED + index))
    result = pd.concat(pieces, ignore_index=True)
    result["分层总数"] = result["抽样分层"].map(sizes).astype(int)
    sampled_counts = result.groupby("抽样分层").size()
    result["抽样权重"] = result.apply(
        lambda row: row["分层总数"] / sampled_counts.loc[row["抽样分层"]], axis=1
    )
    return result.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)


def clean_evidence(sample: pd.DataFrame, raw_rules: dict) -> pd.DataFrame:
    rule_lookup = {item["occupation_id"]: item for item in raw_rules["rules"]}
    sample = sample.copy()
    for index, row in sample.iterrows():
        rule = rule_lookup.get(str(row["candidate_occupation_id"]), {})
        title = normalize(row["job_title_normalized"])
        description = normalize(row["job_description_excerpt"])
        primary = normalize(row["primary_category"])
        excluded = bool(actual_matches(rule.get("title_exclude", []), title))
        title_hits = [] if excluded else actual_matches(rule.get("title_decisive", []), title)
        if not title_hits and not excluded:
            title_hits = actual_matches(rule.get("title_strong", []), title)
        strong_hits = actual_matches(rule.get("description_strong", []), description)
        support_hits = actual_matches(rule.get("description_support", []), description)
        primary_hits = actual_matches(rule.get("primary_patterns", []), primary)
        sample.at[index, "title_evidence"] = "；".join(title_hits)
        sample.at[index, "description_strong_evidence"] = (
            "；".join(strong_hits) if strong_hits or not row["description_strong_evidence"]
            else "完整职位描述后文命中（当前切片未显示）"
        )
        sample.at[index, "description_support_evidence"] = (
            "；".join(support_hits) if support_hits or not row["description_support_evidence"]
            else "完整职位描述后文命中（当前切片未显示）"
        )
        sample.at[index, "primary_evidence"] = "；".join(primary_hits)
    return sample


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def write_workbook(path: Path, frame: pd.DataFrame) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "人工复核"
    headers = list(frame.columns)
    sheet.append(headers)
    for row in frame.itertuples(index=False, name=None):
        sheet.append(list(row))

    dark_blue = "1F4E78"
    light_blue = "D9EAF7"
    input_yellow = "FFF4CC"
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor=dark_blue)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 34
    sheet.freeze_panes = "D2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False

    widths = {
        "A": 9, "B": 18, "C": 22, "D": 22, "E": 15, "F": 23, "G": 13,
        "H": 22, "I": 11, "J": 11, "K": 10, "L": 22, "M": 25, "N": 25,
        "O": 25, "P": 25, "Q": 65, "R": 20, "S": 11, "T": 11,
        "U": 13, "V": 17, "W": 30,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for row_index in range(2, sheet.max_row + 1):
        sheet.row_dimensions[row_index].height = 46
        if row_index % 2 == 0:
            for cell in sheet[row_index]:
                cell.fill = PatternFill("solid", fgColor=light_blue)
        for cell in sheet[row_index]:
            cell.font = Font(name="Arial", size=10, color="1F2937")
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column >= 12)

    judgment_col = headers.index("人工判断") + 1
    correct_col = headers.index("人工正确职业代码") + 1
    note_col = headers.index("人工备注") + 1
    for row_index in range(2, sheet.max_row + 1):
        for column in [judgment_col, correct_col, note_col]:
            sheet.cell(row_index, column).fill = PatternFill("solid", fgColor=input_yellow)
    judgment_letter = sheet.cell(1, judgment_col).column_letter
    validation = DataValidation(
        type="list", formula1='"正确,错误,无法判断"', allow_blank=True
    )
    sheet.add_data_validation(validation)
    validation.add(f"{judgment_letter}2:{judgment_letter}{sheet.max_row}")
    sheet.conditional_formatting.add(
        f"{judgment_letter}2:{judgment_letter}{sheet.max_row}",
        FormulaRule(formula=[f'{judgment_letter}2="正确"'], fill=PatternFill("solid", fgColor="E2F0D9")),
    )
    sheet.conditional_formatting.add(
        f"{judgment_letter}2:{judgment_letter}{sheet.max_row}",
        FormulaRule(formula=[f'{judgment_letter}2="错误"'], fill=PatternFill("solid", fgColor="FCE8E6")),
    )

    notes = workbook.create_sheet("复核说明")
    notes.sheet_view.showGridLines = False
    notes["A1"] = "occupation V4.3 去分差规则实验：人工复核说明"
    notes["A1"].font = Font(name="Arial", size=15, bold=True, color="1F2937")
    instructions = [
        ("实验变化", "只取消第一名领先第二名至少2分的要求；最低得分和独立证据要求不变。"),
        ("样本来源", f"从2022年因分差不足而保留Z99、去掉分差后会新增分类的记录中抽取{len(frame)}条。"),
        ("独立性", "已排除上一轮已经标注的400条记录。"),
        ("人工判断", "判断候选职业代码是否符合岗位的主要工作内容。"),
        ("正确", "候选职业代码正确，不需要填写人工正确职业代码。"),
        ("错误", "候选职业代码错误，请尽量填写正确的37类代码。"),
        ("无法判断", "岗位名称和职位描述仍不足以判断。"),
        ("注意", "不要修改来源记录ID和程序证据列。"),
    ]
    for row_index, (label, value) in enumerate(instructions, start=3):
        notes.cell(row_index, 1, label)
        notes.cell(row_index, 2, value)
        notes.cell(row_index, 1).font = Font(name="Arial", size=11, bold=True, color=dark_blue)
        notes.cell(row_index, 2).font = Font(name="Arial", size=11, color="1F2937")
        notes.cell(row_index, 2).alignment = Alignment(wrap_text=True, vertical="center")
        notes.row_dimensions[row_index].height = 30
    notes.column_dimensions["A"].width = 20
    notes.column_dimensions["B"].width = 85
    temp_path = path.with_suffix(".xlsx.tmp")
    workbook.save(temp_path)
    os.replace(temp_path, path)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    QC_DIR.mkdir(parents=True, exist_ok=True)
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    base_rules = json.loads(BASE_RULE_PATH.read_text(encoding="utf-8"))
    evidence_rules = json.loads(EVIDENCE_RULE_PATH.read_text(encoding="utf-8"))
    experiment = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
    occupation_names = base_rules["occupation_names"]
    l1_names = base_rules["l1_names"]

    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='512MB'")
    audit_sql = str(AUDIT_PATH).replace("\\", "/").replace("'", "''")
    conflicts = connection.execute(f"""
        SELECT *
        FROM read_csv_auto('{audit_sql}', header=true, all_varchar=true)
        WHERE status = 'evidence_conflict_small_margin'
    """).fetchdf()
    for column in ["score_top1", "score_top2", "score_margin"]:
        conflicts[column] = pd.to_numeric(conflicts[column], errors="coerce").fillna(0.0)
    conflicts["new_occupation_name"] = conflicts["candidate_occupation_id"].map(occupation_names)
    conflicts["new_l1"] = conflicts["candidate_occupation_id"].str[0]
    conflicts["new_l1_name"] = conflicts["new_l1"].map(l1_names)
    if conflicts["new_occupation_name"].isna().any():
        raise RuntimeError("去分差候选中存在非法职业代码")

    v42_path = (
        Path(storage["features_root"]) / "occupation_v0.4.2_candidate"
        / "jobs_2022_occupation_v0.4.2_candidate.parquet"
    )
    output_root = Path(storage["features_root"]) / "occupation_v0.4.3_no_margin_candidate"
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "jobs_2022_occupation_v0.4.3_no_margin_candidate.parquet"
    temp_path = output_path.with_suffix(".parquet.tmp")
    temp_path.unlink(missing_ok=True)
    connection.register("no_margin_conflicts", conflicts[[
        "source_record_id", "candidate_occupation_id", "candidate_standard_name",
        "new_occupation_name", "new_l1", "new_l1_name", "score_top1", "score_top2",
        "score_margin",
    ]])
    v42_sql = str(v42_path).replace("\\", "/").replace("'", "''")
    temp_sql = str(temp_path).replace("\\", "/").replace("'", "''")
    version = experiment["version"]
    connection.execute(f"""
        COPY (
            SELECT
                v.source_record_id,
                v.job_title_raw,
                v.job_title_normalized,
                CASE WHEN c.source_record_id IS NOT NULL THEN c.new_l1 ELSE v.occupation_l1 END AS occupation_l1,
                CASE WHEN c.source_record_id IS NOT NULL THEN c.new_l1_name ELSE v.occupation_l1_name END AS occupation_l1_name,
                CASE WHEN c.source_record_id IS NOT NULL THEN c.candidate_occupation_id ELSE v.occupation_id END AS occupation_id,
                CASE WHEN c.source_record_id IS NOT NULL THEN c.new_occupation_name ELSE v.occupation_name END AS occupation_name,
                CASE WHEN c.source_record_id IS NOT NULL THEN c.candidate_standard_name ELSE v.occupation_standard_name END AS occupation_standard_name,
                CASE WHEN c.source_record_id IS NOT NULL THEN 'no_margin_evidence_candidate' ELSE v.occupation_method END AS occupation_method,
                CASE WHEN c.source_record_id IS NOT NULL THEN 'V043_NO_MARGIN_EXPERIMENT' ELSE v.occupation_rule_id END AS occupation_rule_id,
                CASE WHEN c.source_record_id IS NOT NULL THEN 'manual_review_required' ELSE v.occupation_confidence END AS occupation_confidence,
                CASE WHEN c.source_record_id IS NOT NULL THEN 'v043_no_margin_accepted' ELSE v.occupation_status END AS occupation_status,
                CAST(CASE WHEN c.source_record_id IS NOT NULL THEN 1 ELSE v.occupation_review_flag END AS TINYINT) AS occupation_review_flag,
                CAST(CASE WHEN c.source_record_id IS NOT NULL THEN c.score_top1 ELSE v.occupation_score_top1 END AS FLOAT) AS occupation_score_top1,
                CAST(CASE WHEN c.source_record_id IS NOT NULL THEN c.score_top2 ELSE v.occupation_score_top2 END AS FLOAT) AS occupation_score_top2,
                CAST(CASE WHEN c.source_record_id IS NOT NULL THEN c.score_margin ELSE v.occupation_score_margin END AS FLOAT) AS occupation_score_margin,
                '{version}' AS occupation_version,
                v.v03_occupation_id,
                v.v03_occupation_name
            FROM read_parquet('{v42_sql}') v
            LEFT JOIN no_margin_conflicts c USING (source_record_id)
        ) TO '{temp_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    os.replace(temp_path, output_path)

    annotated_ids = load_annotated_ids()
    eligible = conflicts.loc[~conflicts["source_record_id"].isin(annotated_ids)].copy()
    sample = stratified_sample(eligible, min(SAMPLE_SIZE, len(eligible)))
    sample = clean_evidence(sample, evidence_rules)
    sample.insert(0, "复核序号", range(1, len(sample) + 1))
    sample["V4.2原状态"] = "类别冲突、分差不足，保留Z99"
    sample["去分差后是否接受"] = "是"
    sample["人工判断"] = ""
    sample["人工正确职业代码"] = ""
    sample["人工备注"] = ""
    review_columns = [
        "复核序号", "source_record_id", "job_title_raw", "job_title_normalized",
        "primary_category", "V4.2原状态", "去分差后是否接受",
        "candidate_occupation_id", "new_occupation_name", "score_top1", "score_top2",
        "score_margin", "title_evidence", "description_strong_evidence",
        "description_support_evidence", "fuzzy_evidence", "job_description_excerpt",
        "抽样分层", "分层总数", "抽样权重", "人工判断", "人工正确职业代码", "人工备注",
    ]
    review = sample[review_columns].rename(columns={
        "source_record_id": "来源记录ID",
        "job_title_raw": "原始岗位名称",
        "job_title_normalized": "标准化岗位名称",
        "primary_category": "原始初级分类",
        "candidate_occupation_id": "候选职业代码",
        "new_occupation_name": "候选职业名称",
        "score_top1": "第一名得分",
        "score_top2": "第二名得分",
        "score_margin": "原分差",
        "title_evidence": "岗位名称证据",
        "description_strong_evidence": "职位描述强证据",
        "description_support_evidence": "职位描述辅助证据",
        "fuzzy_evidence": "模糊名称辅助证据",
        "job_description_excerpt": "职位描述切片",
    })
    review_csv = OUTPUT_DIR / "occupation_v043_no_margin_2022_独立复核样本_300条.csv"
    review_xlsx = OUTPUT_DIR / "occupation_v043_no_margin_2022_独立复核样本_300条.xlsx"
    write_csv(review_csv, review)
    write_workbook(review_xlsx, review)

    old_classified = int(connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{v42_sql}') WHERE occupation_id <> 'Z99'"
    ).fetchone()[0])
    output_sql = str(output_path).replace("\\", "/").replace("'", "''")
    new_classified = int(connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{output_sql}') WHERE occupation_id <> 'Z99'"
    ).fetchone()[0])
    total = int(connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{output_sql}')"
    ).fetchone()[0])
    changed_existing = int(connection.execute(f"""
        SELECT COUNT(*)
        FROM read_parquet('{v42_sql}') old
        JOIN read_parquet('{output_sql}') new USING (source_record_id)
        WHERE old.occupation_id <> 'Z99' AND old.occupation_id <> new.occupation_id
    """).fetchone()[0])
    invalid_codes = int(connection.execute(f"""
        SELECT COUNT(*) FROM read_parquet('{output_sql}')
        WHERE occupation_id NOT IN ({','.join(repr(code) for code in occupation_names)})
    """).fetchone()[0])
    sample_overlap = len(set(review["来源记录ID"].astype(str)) & annotated_ids)
    marker_count = int(
        review[["岗位名称证据", "职位描述强证据", "职位描述辅助证据"]]
        .astype(str).apply(lambda column: column.str.contains(r"\(\?:|\.\{|\[\^|\\[+*?.]", regex=True).sum()).sum()
    )

    summary = pd.DataFrame([{
        "year": 2022,
        "records": total,
        "v42_classified": old_classified,
        "v42_coverage": old_classified / total,
        "newly_classified_by_removing_margin": len(conflicts),
        "v43_no_margin_classified": new_classified,
        "v43_no_margin_coverage": new_classified / total,
        "coverage_change_percentage_points": (new_classified - old_classified) / total * 100,
        "remaining_z99": total - new_classified,
        "changed_existing_v42_classifications": changed_existing,
        "invalid_codes": invalid_codes,
        "previously_annotated_ids_excluded": len(annotated_ids),
        "eligible_new_review_population": len(eligible),
        "review_sample_rows": len(review),
        "review_sample_overlap_with_previous_400": sample_overlap,
        "regex_markers_in_review_evidence": marker_count,
        "candidate_output": str(output_path),
    }])
    summary_path = QC_DIR / "occupation_v043_no_margin_2022_summary.csv"
    write_csv(summary_path, summary)

    code_distribution = (
        conflicts.groupby(["candidate_occupation_id", "new_occupation_name"], dropna=False)
        .size().rename("new_records").reset_index().sort_values("new_records", ascending=False)
    )
    write_csv(QC_DIR / "occupation_v043_no_margin_2022_new_code_distribution.csv", code_distribution)
    margin_distribution = (
        conflicts.assign(margin_band=conflicts["score_margin"].map(margin_band))
        .groupby("margin_band").size().rename("new_records").reset_index()
    )
    write_csv(QC_DIR / "occupation_v043_no_margin_2022_margin_distribution.csv", margin_distribution)

    report_path = QC_DIR / "occupation_v043_no_margin_2022_report.md"
    report_path.write_text(f"""# occupation V4.3 去分差规则：2022年实验报告

## 实验设置

- 只取消“第一名至少领先第二名2分”的要求；
- 最低总分5分和独立证据要求保持不变；
- 不覆盖V4.1或V4.2；
- 本实验版暂不用于回归。

## 结果

- 2022年总记录：{total:,}条；
- V4.2覆盖率：{old_classified / total:.2%}；
- 取消分差后新增分类：{len(conflicts):,}条；
- V4.3无分差候选覆盖率：{new_classified / total:.2%}；
- 覆盖率增加：{(new_classified - old_classified) / total * 100:.2f}个百分点；
- 仍为Z99：{total - new_classified:,}条；
- V4.2既有分类被修改：{changed_existing}条。

## 新复核样本

- 从新增分类记录中抽取{len(review)}条；
- 已排除上一轮标注的{len(annotated_ids)}条记录；
- 与上一轮样本重叠：{sample_overlap}条；
- 证据列正则表达式残留：{marker_count}处；
- 样本采用“候选职业代码×原分差”分层抽样，表中保留抽样权重。

只有在新样本复核后，才能判断是否将取消分差规则纳入正式V4.3。
""", encoding="utf-8")

    checks = {
        "rows_equal_328548": total == 328_548,
        "new_classification_count_matches": new_classified - old_classified == len(conflicts),
        "no_existing_v42_change": changed_existing == 0,
        "valid_codes": invalid_codes == 0,
        "sample_size_300": len(review) == SAMPLE_SIZE,
        "sample_unique_ids": review["来源记录ID"].nunique() == len(review),
        "sample_independent": sample_overlap == 0,
        "readable_evidence": marker_count == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"实验校验失败: {checks}")
    print(f"TOTAL={total}")
    print(f"V42_COVERAGE={old_classified / total:.6f}")
    print(f"NEW_NO_MARGIN={len(conflicts)}")
    print(f"V43_COVERAGE={new_classified / total:.6f}")
    print(f"SAMPLE={len(review)}")
    print(f"OUTPUT={output_path}")
    print(f"REVIEW={review_xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
