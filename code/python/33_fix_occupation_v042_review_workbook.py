"""低内存修复V4.2人工复核工作簿中的内部正则表达式显示。"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118"
CSV_PATH = OUTPUT_DIR / "occupation_v042_2022_manual_review_sample_400.csv"
XLSX_PATH = OUTPUT_DIR / "occupation_v042_2022_人工复核样本_400条.xlsx"

HEADERS = [
    "复核序号", "来源记录ID", "原始岗位名称", "标准化岗位名称", "原始初级分类",
    "V4.1未分类原因", "V4.1模糊匹配最高分", "V4.2是否接受", "V4.2处理状态",
    "候选职业代码", "候选职业名称", "证据方法", "置信度", "第一名得分", "第二名得分",
    "领先分差", "岗位名称证据", "职位描述强证据", "职位描述辅助证据",
    "初级分类辅助证据", "模糊名称辅助证据", "职位描述切片", "人工判断",
    "人工正确职业代码", "人工备注",
]

SOURCE_COLUMNS = [
    "复核序号", "source_record_id", "job_title_raw", "job_title_normalized", "primary_category",
    "occupation_status", "occupation_score_top1", "accepted", "status",
    "candidate_occupation_id", "candidate_standard_name", "method", "confidence", "score_top1",
    "score_top2", "score_margin", "title_evidence", "description_strong_evidence",
    "description_support_evidence", "primary_evidence", "fuzzy_evidence",
    "job_description_excerpt", "人工判断", "人工正确职业代码", "人工备注",
]

STATUS_MAP = {
    "score_below_80": "模糊匹配低于80分",
    "fuzzy_80_89_review": "模糊匹配80—89分，待复核",
    "short_title_blocked": "岗位名称过短",
    "short_ascii_blocked": "英文缩写过短",
    "ambiguous_title_needs_context": "岗位名称有歧义，需要上下文",
    "empty_or_advertising_title": "岗位名称为空或仅为广告语",
}
RESULT_MAP = {
    "v042_evidence_accepted": "已接受新增分类",
    "insufficient_independent_evidence": "独立证据不足，保留Z99",
    "no_evidence": "没有命中证据，保留Z99",
    "score_below_threshold": "证据得分不足，保留Z99",
    "evidence_conflict_small_margin": "类别冲突，分差不足，保留Z99",
}
METHOD_MAP = {
    "decisive_title_and_description": "高精度名称＋职位描述",
    "decisive_title_rule": "高精度岗位名称",
    "title_and_description_evidence": "岗位名称＋职位描述",
    "description_multi_evidence": "多项职位描述证据",
    "fuzzy_name_and_description_evidence": "模糊名称＋职位描述",
    "title_multi_evidence": "岗位名称多重证据",
    "title_and_primary_confirmation": "岗位名称＋初级分类辅助",
    "v042_evidence_not_accepted": "证据不足，未接受",
}
CONFIDENCE_MAP = {"high": "高", "medium": "中", "unclassified": "未分类"}


def display_value(source_column: str, value: str) -> str:
    if source_column == "occupation_status":
        return STATUS_MAP.get(value, value)
    if source_column == "accepted":
        return "是" if value == "True" else "否"
    if source_column == "status":
        return RESULT_MAP.get(value, value)
    if source_column == "method":
        return METHOD_MAP.get(value, value)
    if source_column == "confidence":
        return CONFIDENCE_MAP.get(value, value)
    return value


def main() -> int:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 400:
        raise RuntimeError(f"复核样本应为400条，实际{len(rows)}条")

    workbook = load_workbook(XLSX_PATH)
    sheet = workbook["人工复核"]
    for column_index, header in enumerate(HEADERS, start=1):
        sheet.cell(1, column_index, header)
    for row_index, source in enumerate(rows, start=2):
        for column_index, source_column in enumerate(SOURCE_COLUMNS, start=1):
            sheet.cell(row_index, column_index, display_value(source_column, source[source_column]))

    marker = re.compile(r"\(\?:|\.\{|\[\^|\\[+*?.]")
    marker_count = 0
    for row in sheet.iter_rows(min_row=2, max_row=401, min_col=17, max_col=20):
        marker_count += sum(bool(marker.search(str(cell.value or ""))) for cell in row)
    if marker_count:
        raise RuntimeError(f"证据列仍有{marker_count}个正则表达式标记")

    temp_path = XLSX_PATH.with_suffix(".xlsx.tmp")
    workbook.save(temp_path)
    output_path = XLSX_PATH
    try:
        os.replace(temp_path, XLSX_PATH)
    except PermissionError:
        output_path = XLSX_PATH.with_name(f"{XLSX_PATH.stem}_已修复.xlsx")
        os.replace(temp_path, output_path)
    print(f"ROWS={len(rows)}")
    print(f"REGEX_MARKERS_REMAINING={marker_count}")
    print(f"OUTPUT={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
