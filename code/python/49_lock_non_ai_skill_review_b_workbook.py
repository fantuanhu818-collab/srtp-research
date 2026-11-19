"""将三类非AI技能人工复核表处理为B复核员专用的受保护版本。

Artifact Tool负责工作簿内容与格式。本脚本只补充其当前未提供的Excel工作表保护：
所有单元格默认锁定，仅开放分配给B或A+B记录的B判定区（L:O）。
"""

from __future__ import annotations

import copy
import json
import os
import posixpath
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
WORKBOOK_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "non_ai_skill_review_20261119"
    / "三类非AI技能人工复核表_2022_v0.1_B专用.xlsx"
)
DATA_PATH = (
    PROJECT_ROOT / "outputs" / "qc" / "non_ai_skill_unified_review_2022_v0.1.json"
)
VALIDATION_PATH = (
    PROJECT_ROOT / "outputs" / "qc" / "non_ai_skill_review_b_lock_validation.json"
)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)


def qname(local_name: str) -> str:
    return f"{{{MAIN_NS}}}{local_name}"


def relationship_qname(local_name: str) -> str:
    return f"{{{REL_NS}}}{local_name}"


def workbook_sheet_paths(files: dict[str, bytes]) -> dict[str, str]:
    workbook = ET.fromstring(files["xl/workbook.xml"])
    relationships = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.find(qname("sheets")):
        relationship_id = sheet.get(relationship_qname("id"))
        target = targets[relationship_id]
        path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        result[sheet.get("name")] = path
    return result


def make_unlocked_style_map(
    styles_root: ET.Element, original_style_ids: set[int]
) -> dict[int, int]:
    cell_xfs = styles_root.find(qname("cellXfs"))
    xfs = list(cell_xfs)
    mapping: dict[int, int] = {}
    for original_style_id in sorted(original_style_ids):
        unlocked = copy.deepcopy(xfs[original_style_id])
        unlocked.set("applyProtection", "1")
        for protection in unlocked.findall(qname("protection")):
            unlocked.remove(protection)
        ET.SubElement(unlocked, qname("protection"), {"locked": "0", "hidden": "0"})
        mapping[original_style_id] = len(cell_xfs)
        cell_xfs.append(unlocked)
    cell_xfs.set("count", str(len(cell_xfs)))
    return mapping


def add_sheet_protection(sheet_root: ET.Element) -> None:
    existing = sheet_root.find(qname("sheetProtection"))
    if existing is not None:
        sheet_root.remove(existing)

    protection = ET.Element(
        qname("sheetProtection"),
        {
            "sheet": "1",
            "objects": "1",
            "scenarios": "1",
            "formatCells": "1",
            "formatColumns": "1",
            "formatRows": "1",
            "insertColumns": "1",
            "insertRows": "1",
            "insertHyperlinks": "1",
            "deleteColumns": "1",
            "deleteRows": "1",
            "selectLockedCells": "0",
            "sort": "0",
            "autoFilter": "0",
            "pivotTables": "1",
            "selectUnlockedCells": "0",
        },
    )
    preceding = {
        "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
        "sheetCalcPr",
    }
    children = list(sheet_root)
    insert_at = len(children)
    for index, child in enumerate(children):
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name not in preceding:
            insert_at = index
            break
    sheet_root.insert(insert_at, protection)


def main() -> None:
    rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    editable_excel_rows = {
        int(row["sample_no"]) + 5
        for row in rows
        if row["assigned_reviewer"] in {"B", "A+B"}
    }
    if len(editable_excel_rows) != 150:
        raise ValueError(f"B应复核150条，实际得到{len(editable_excel_rows)}条")

    with ZipFile(WORKBOOK_PATH, "r") as source_zip:
        infos = source_zip.infolist()
        files = {info.filename: source_zip.read(info.filename) for info in infos}

    sheet_paths = workbook_sheet_paths(files)
    required_sheets = {"填写说明", "人工复核", "程序结果"}
    if not required_sheets.issubset(sheet_paths):
        raise ValueError(f"工作簿缺少工作表：{sorted(required_sheets - set(sheet_paths))}")

    manual_path = sheet_paths["人工复核"]
    manual_root = ET.fromstring(files[manual_path])
    cell_map = {cell.get("r"): cell for cell in manual_root.iter(qname("c"))}
    editable_addresses = {
        f"{column}{excel_row}"
        for excel_row in editable_excel_rows
        for column in ("L", "M", "N", "O")
    }
    missing = sorted(address for address in editable_addresses if address not in cell_map)
    if missing:
        raise ValueError(f"B输入区有{len(missing)}个单元格未写入工作表：{missing[:10]}")

    original_style_ids = {int(cell_map[address].get("s", "0")) for address in editable_addresses}
    styles_root = ET.fromstring(files["xl/styles.xml"])
    unlocked_style_map = make_unlocked_style_map(styles_root, original_style_ids)
    for address in editable_addresses:
        cell = cell_map[address]
        original_style_id = int(cell.get("s", "0"))
        cell.set("s", str(unlocked_style_map[original_style_id]))

    add_sheet_protection(manual_root)
    files[manual_path] = ET.tostring(manual_root, encoding="utf-8", xml_declaration=True)
    files["xl/styles.xml"] = ET.tostring(styles_root, encoding="utf-8", xml_declaration=True)

    for sheet_name in ("填写说明", "程序结果"):
        path = sheet_paths[sheet_name]
        root = ET.fromstring(files[path])
        add_sheet_protection(root)
        files[path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    WORKBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="non_ai_review_b_", suffix=".xlsx", dir=WORKBOOK_PATH.parent, delete=False
    ) as temp_handle:
        temp_path = Path(temp_handle.name)
    try:
        with ZipFile(temp_path, "w", compression=ZIP_DEFLATED) as target_zip:
            for info in infos:
                target_zip.writestr(info, files[info.filename])
        os.replace(temp_path, WORKBOOK_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    with ZipFile(WORKBOOK_PATH, "r") as check_zip:
        check_files = {name: check_zip.read(name) for name in check_zip.namelist()}
    check_sheet_paths = workbook_sheet_paths(check_files)
    check_styles = ET.fromstring(check_files["xl/styles.xml"])
    cell_xfs = list(check_styles.find(qname("cellXfs")))
    check_manual = ET.fromstring(check_files[check_sheet_paths["人工复核"]])
    check_cells = {cell.get("r"): cell for cell in check_manual.iter(qname("c"))}

    def cell_is_unlocked(address: str) -> bool:
        style_id = int(check_cells[address].get("s", "0"))
        protection = cell_xfs[style_id].find(qname("protection"))
        return protection is not None and protection.get("locked") == "0"

    expected_unlocked = all(cell_is_unlocked(address) for address in editable_addresses)
    a_area_locked = all(
        not cell_is_unlocked(f"{column}{excel_row}")
        for excel_row in range(6, 246)
        for column in ("H", "I", "J", "K")
    )
    b_not_assigned_rows = set(range(6, 246)) - editable_excel_rows
    b_unassigned_locked = all(
        not cell_is_unlocked(f"{column}{excel_row}")
        for excel_row in b_not_assigned_rows
        for column in ("L", "M", "N", "O")
    )
    protection_by_sheet = {
        sheet_name: ET.fromstring(check_files[path]).find(qname("sheetProtection")) is not None
        for sheet_name, path in check_sheet_paths.items()
        if sheet_name in required_sheets
    }

    validation = {
        "workbook": str(WORKBOOK_PATH),
        "editable_b_rows": len(editable_excel_rows),
        "editable_b_cells": len(editable_addresses),
        "checks": {
            "B或A+B记录的B输入区全部可编辑": expected_unlocked,
            "A输入区全部锁定": a_area_locked,
            "仅A复核记录的B输入区全部锁定": b_unassigned_locked,
            "三个工作表均启用保护": all(protection_by_sheet.values()),
        },
        "sheet_protection": protection_by_sheet,
        "note": "工作表保护未设置密码，用于防止误填，不作为安全控制。",
    }
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not all(validation["checks"].values()):
        raise ValueError(f"工作簿锁定校验失败：{validation}")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
