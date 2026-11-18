"""把标注表CSV做成便于填写的Excel工作簿（11-19）。

参照A的职业复核工作簿：下拉选项、自动标红、进度统计、填写说明；只有三列可填，其余锁定。
列名和列顺序与CSV完全一致（编号、招聘岗位、职位描述、1/0/9、AI类型、备注），
15_score_annotation.py 优先读取这里生成的xlsx。

输入：<analysis_root>/ai_annotation_v0.2/标注表_A.csv、标注表_B.csv
输出：同目录 标注表_A.xlsx、标注表_B.xlsx（含广告原文，不进Git）
用法：.venv/bin/python code/python/32_make_annotation_xlsx.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[2]
storage = json.loads((ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
DIR = Path(storage["analysis_root"]) / "ai_annotation_v0.2"

LABEL = "是否要求AI技能(1/0/9)"
AI_TYPE = "AI类型(traditional/generative/both)"
COLUMNS = ["编号", "招聘岗位", "职位描述", LABEL, AI_TYPE, "备注"]
TAGS = ["仅专业", "标注类", "AI工具使用", "仅标题", "仅算法岗", "否定"]
WIDTHS = {"A": 7, "B": 22, "C": 95, "D": 12, "E": 16, "F": 18}

HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF8E1")   # 待填写列底色
GREEN = PatternFill("solid", fgColor="C8E6C9")
GREY = PatternFill("solid", fgColor="E0E0E0")
YELLOW = PatternFill("solid", fgColor="FFE082")
RED = PatternFill("solid", fgColor="EF9A9A")
THIN = Border(bottom=Side(style="thin", color="BDBDBD"))


def readable(text: str) -> str:
    """只为便于阅读：把HTML换行标签换成换行，去掉其他标签。不改变判断所需的文字。"""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", str(text))
    text = re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ")
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:32000]


def sheet_main(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.active
    ws.title = "标注"
    ws.append(COLUMNS)
    for _, r in df.iterrows():
        ws.append([int(r["编号"]), r["招聘岗位"], readable(r["职位描述"]), None, None, None])
    n = len(df) + 1
    for col, w in WIDTHS.items():
        ws.column_dimensions[col].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 34
    for row in ws.iter_rows(min_row=2, max_row=n):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = THIN
        for cell in row[3:6]:
            cell.fill = INPUT_FILL
            cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
            cell.protection = Protection(locked=False)
    ws.freeze_panes = "D2"

    dv_label = DataValidation(type="list", formula1='"1,0,9"', allow_blank=True,
                              errorTitle="只能填1、0、9", error="1=要求AI技能，0=不要求，9=无法判断")
    dv_type = DataValidation(type="list", formula1='"traditional,generative,both"', allow_blank=True,
                             errorTitle="AI类型", error="只能选traditional、generative、both；标0或9时留空")
    dv_note = DataValidation(type="list", formula1='"' + ",".join(TAGS) + '"', allow_blank=True,
                             showErrorMessage=False)  # 可选固定标签，也可以手写
    for dv, col in ((dv_label, "D"), (dv_type, "E"), (dv_note, "F")):
        dv.add(f"{col}2:{col}{n}")
        ws.add_data_validation(dv)

    rng = f"D2:D{n}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=["$D2=1"], fill=GREEN))
    ws.conditional_formatting.add(rng, FormulaRule(formula=["$D2=0"], fill=GREY))
    ws.conditional_formatting.add(rng, FormulaRule(formula=["$D2=9"], fill=YELLOW))
    # 标1没填类型、标0/9却填了类型 → 类型格标红
    ws.conditional_formatting.add(f"E2:E{n}", FormulaRule(formula=['AND($D2=1,$E2="")'], fill=RED))
    ws.conditional_formatting.add(f"E2:E{n}", FormulaRule(formula=['AND(OR($D2=0,$D2=9),$E2<>"")'], fill=RED))
    ws.protection.sheet = True
    ws.protection.formatCells = False
    ws.protection.formatRows = False      # 允许调行高
    ws.protection.formatColumns = False   # 允许调列宽
    ws.protection.autoFilter = False


def sheet_progress(wb: Workbook, n: int) -> None:
    ws = wb.create_sheet("进度")
    last = n + 1
    rows = [
        ("总条数", n),
        ("已填写", f"=COUNT(标注!D2:D{last})"),
        ("未填写", f"={n}-B3"),
        ("完成比例", "=B3/B2"),
        ("", ""),
        ("标1（要求AI技能）", f"=COUNTIF(标注!D2:D{last},1)"),
        ("标0（不要求）", f"=COUNTIF(标注!D2:D{last},0)"),
        ("标9（无法判断）", f"=COUNTIF(标注!D2:D{last},9)"),
        ("", ""),
        ("需修改：标1但没填AI类型", f'=COUNTIFS(标注!D2:D{last},1,标注!E2:E{last},"")'),
        ("需修改：标0/9却填了AI类型", f'=COUNTIFS(标注!D2:D{last},0,标注!E2:E{last},"<>")+COUNTIFS(标注!D2:D{last},9,标注!E2:E{last},"<>")'),
        ("", ""),
        ("交回条件", '=IF(AND(B4=0,B11=0,B12=0),"可以交回","还没完成")'),
    ]
    ws.append(["项目", "数量"])
    for r in rows:
        ws.append(list(r))
    ws["B5"].number_format = "0%"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 14
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
    for r in (11, 12):
        ws[f"A{r}"].font = Font(color="C62828")
    ws["A14"].font = ws["B14"].font = Font(bold=True)
    ws.protection.sheet = True


GUIDE = [
    ("怎么填", ""),
    ("只填黄色三列", "D列1/0/9、E列AI类型、F列备注，都可以从下拉里选。其他列锁定，不要改顺序。"),
    ("只看原文", "表里看不到程序结果，标完之前不要打开答案表，也不要猜程序会怎么判。"),
    ("重叠样本", "有50条两人都标，随机混在表里；标完之前不讨论。"),
    ("", ""),
    ("什么时候标1", "满足任一条：要求掌握/熟悉/了解AI技术、算法、框架或工具；职责包括开发、训练、部署、调优AI模型或应用；要求使用AI工具完成工作；AI经验列为优先或加分。"),
    ("什么时候标0", "AI只出现在公司/产品/行业介绍里；“AI”是别的意思（Illustrator、CV是简历、Transformer是变压器）；泛泛提到AI，不构成技能要求。"),
    ("什么时候标9", "原文信息不够，确实分不出来（如“负责机器视觉相关工作”看不出是算法还是设备）。不要猜。"),
    ("", ""),
    ("AI类型", "traditional：机器学习、深度学习、CV、NLP、推荐算法等；generative：大模型、ChatGPT、AIGC、提示词、RAG、智能体等；both：两类都有；标0或9留空。"),
    ("", ""),
    ("备注固定标签", "遇到下面几种情况，备注一定要写对应标签（可在下拉里选）："),
    ("仅专业", "只要求“计算机、人工智能等相关专业”，没有技能要求 → 标0"),
    ("标注类", "数据标注、AI训练师等，只做简单标注 → 标0"),
    ("AI工具使用", "只要求会用ChatGPT等AI工具处理办公事务 → 标1，类型generative"),
    ("仅标题", "只有岗位名称是AI岗（如“机器学习工程师”），描述里没有AI词 → 标1"),
    ("仅算法岗", "“算法工程师”，描述里没有任何AI词 → 标0"),
    ("否定", "AI词前有“无需/不要求”，或后有“不作要求/非必须” → 标0；“不限”“者优先”不算否定"),
    ("", ""),
    ("颜色", "D列：绿=1，灰=0，黄=9。E列标红=AI类型漏填或多填，需要改。“进度”页显示完成情况，出现“可以交回”再交。"),
    ("交回", "原文件名发回B，不改列名、不调行序。详细口径见《AI技能标注对齐说明_v0.2》第三部分。"),
]


def sheet_guide(wb: Workbook) -> None:
    ws = wb.create_sheet("填写说明", 0)
    for a, b in GUIDE:
        ws.append([a, b])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 110
    for row in ws.iter_rows():
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    for r in (1, 12):
        ws[f"A{r}"].font = Font(bold=True, size=13, color="1F4E78")


def main() -> int:
    for who in "AB":
        df = pd.read_csv(DIR / f"标注表_{who}.csv", encoding="utf-8-sig", dtype=str)
        assert list(df.columns) == COLUMNS, df.columns
        assert df[LABEL].isna().all(), f"标注表_{who}.csv 已有填写内容，不覆盖"
        wb = Workbook()
        sheet_main(wb, df)
        sheet_progress(wb, len(df))
        sheet_guide(wb)
        wb.active = 1  # 打开时停在“标注”页
        out = DIR / f"标注表_{who}.xlsx"
        wb.save(out)
        print(f"{who}: rows={len(df)} -> {out}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
