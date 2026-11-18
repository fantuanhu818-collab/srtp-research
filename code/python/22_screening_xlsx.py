"""把第4步筛词表（CSV）转成便于阅读和填写的Excel（格式参照数据分析线的 occupation_manual_review 表）。

不改编号和行序：Excel第6行起逐行对应CSV的编号1—400，两种格式填好的结果都能被 19_merge_screening.py 读取。
新增“影响”一列：单独出现（不含现有严格词）的广告≥100条记为“重点”，这120个词占全部新增影响的98%；
不给建议层级，避免影响判断。
新增“负责”一列（11-18折中方案，分配规则见 19_merge_screening.assignment）：重点词两人都筛；其余280个按编号顺序
交替分给A、B，各140个。不归自己负责的行显示为灰色、填写状态为“无需填写”。

输入：<analysis_root>/ai_w2v_screening_v0.2/筛词表_A.csv、筛词表_B.csv
输出：同目录 筛词表_A.xlsx、筛词表_B.xlsx（含广告原句，不进Git）

运行：.venv/bin/python code/python/22_screening_xlsx.py
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
assignment = importlib.import_module("19_merge_screening").assignment
WHO_ZH = {"AB": "两人", "A": "仅A", "B": "仅B"}
GRAY_FILL = PatternFill("solid", fgColor="F3F4F6")
RESULT_COL = "筛选结果(1严格/2条件/3宽泛/0不加入)"
KEY_MIN_ALONE = 100
HEADER_ROW, FIRST = 5, 6

INK, MUTED = "1F2937", "6B7280"
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
SUB_FILL = PatternFill("solid", fgColor="D9EAF7")
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")
FILL_COL = PatternFill("solid", fgColor="FFFBEA")  # 需要填写的两列
THIN = Side(style="thin", color="D1D5DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
F = Font(name="微软雅黑", size=10, color=INK)
FB = Font(name="微软雅黑", size=10, color=INK, bold=True)
FH = Font(name="微软雅黑", size=10, color="FFFFFF", bold=True)
FT = Font(name="微软雅黑", size=13, color=INK, bold=True)
FM = Font(name="微软雅黑", size=10, color=MUTED)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="top", wrap_text=True)

# (表头, 宽度, 取值函数, 对齐)
COLUMNS = [
    ("编号", 6, lambda r: int(r["编号"]), CENTER),
    ("影响", 7, lambda r: "重点" if int(r["不含现有严格词的广告数"]) >= KEY_MIN_ALONE else "影响小", CENTER),
    ("负责", 7, lambda r: WHO_ZH[r["_who"]], CENTER),
    ("候选词", 16, lambda r: r["候选词"], WRAP),
    ("来源组", 11, lambda r: r["来源组"].replace("|", "、"), WRAP),
    ("最接近的种子词", 14, lambda r: r["最接近的种子词"], WRAP),
    ("相似度", 7, lambda r: float(r["最高相似度"]), CENTER),
    ("广告数\nChatGPT前", 9, lambda r: int(r["出现广告数_ChatGPT前"]), CENTER),
    ("广告数\nChatGPT后", 9, lambda r: int(r["出现广告数_ChatGPT后"]), CENTER),
    ("单独出现\n广告数", 9, lambda r: int(r["不含现有严格词的广告数"]), CENTER),
    ("共现\n相关度", 8, lambda r: r["共现相关度"], CENTER),
    ("例句1", 46, lambda r: r["例句1"], WRAP),
    ("例句2", 46, lambda r: r["例句2"], WRAP),
    ("例句3", 46, lambda r: r["例句3"], WRAP),
    ("筛选结果\n1严格 2条件\n3宽泛 0不加入", 12, lambda r: (int(r[RESULT_COL]) if r[RESULT_COL].strip() in {"0", "1", "2", "3"} else None), CENTER),
    ("备注", 26, lambda r: r["备注"] or None, WRAP),
    ("填写状态", 9, None, CENTER),
]
COL = {name.split("\n")[0]: i + 1 for i, (name, *_) in enumerate(COLUMNS)}
LETTER = {k: chr(64 + v) for k, v in COL.items()}


def rich_example(text: str) -> CellRichText | str:
    """标签（单独出现/有其他AI词）灰色，【候选词】加粗红色。"""
    if not text:
        return ""
    parts, pos = [], 0
    m = re.match(r"（[^）]*）", text)
    if m:
        color = "B45309" if "单独" in m.group() else MUTED
        parts.append(TextBlock(InlineFont(rFont="微软雅黑", sz=10, color=color, b=True), m.group()))
        pos = m.end()
    for hit in re.finditer(r"【[^】]*】", text[pos:]):
        s, e = pos + hit.start(), pos + hit.end()
        if text[pos:s]:
            parts.append(TextBlock(InlineFont(rFont="微软雅黑", sz=10, color=INK), text[pos:s]))
        parts.append(TextBlock(InlineFont(rFont="微软雅黑", sz=10, color="C00000", b=True), text[s:e]))
        pos = e
    if text[pos:]:
        parts.append(TextBlock(InlineFont(rFont="微软雅黑", sz=10, color=INK), text[pos:]))
    return CellRichText(parts)


def title(ws, text: str, sub: str) -> None:
    ws["A2"], ws["A3"] = text, sub
    ws["A2"].font, ws["A3"].font = FT, FM
    ws.sheet_view.showGridLines = False


def header(ws, row: int, names: list[str]) -> None:
    for j, name in enumerate(names, 1):
        c = ws.cell(row, j, name)
        c.font, c.fill, c.alignment = FH, HEAD_FILL, Alignment(horizontal="center", vertical="center", wrap_text=True)


def table(ws, row: int, rows: list[list], widths: list[int] | None = None) -> int:
    for i, vals in enumerate(rows):
        for j, v in enumerate(vals, 1):
            c = ws.cell(row + i, j, v)
            c.font, c.alignment, c.border = F, WRAP, BORDER
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + j)].width = w
    return row + len(rows)


def build(rows: list[dict], who: str, out: Path) -> None:
    wb = Workbook()
    n = len(rows)
    last = FIRST + n - 1
    res, stat, imp, own = LETTER["筛选结果"], LETTER["填写状态"], LETTER["影响"], LETTER["负责"]
    other = "仅B" if who == "A" else "仅A"
    n_mine = sum(who in r["_who"] for r in rows)
    n_key = sum(r["_who"] == "AB" for r in rows)

    # ---- 填写进度 ----
    ws = wb.active
    ws.title = "填写进度"
    ws.sheet_properties.tabColor = "70AD47"
    title(ws, f"候选词筛选进度（筛选人：{who}）", "在“筛词表”页填写后，本页自动统计。")
    header(ws, 5, ["指标", f"我负责的（{who}）", "其中：重点词", "说明"])
    rng = lambda c: f"'筛词表'!${c}${FIRST}:${c}${last}"  # noqa: E731
    mine = f'{rng(own)},"<>{other}"'
    stats = [
        ["要筛的词数", n_mine, n_key, f"重点词{n_key}个两人都筛；其余{n - n_key}个影响小的词按编号交替分给A、B，你负责{n_mine - n_key}个"],
        ["已填写", f'=COUNTIF({rng(stat)},"已填写")', f'=COUNTIFS({rng(imp)},"重点",{rng(stat)},"已填写")', "筛选结果已填0/1/2/3"],
        ["未填写", "=B6-B7", "=C6-C7", "仍需要处理"],
        ["1 严格", f"=COUNTIFS({mine},{rng(res)},1)", f'=COUNTIFS({rng(imp)},"重点",{rng(res)},1)', ""],
        ["2 条件", f"=COUNTIFS({mine},{rng(res)},2)", f'=COUNTIFS({rng(imp)},"重点",{rng(res)},2)', ""],
        ["3 宽泛", f"=COUNTIFS({mine},{rng(res)},3)", f'=COUNTIFS({rng(imp)},"重点",{rng(res)},3)', ""],
        ["0 不加入", f"=COUNTIFS({mine},{rng(res)},0)", f'=COUNTIFS({rng(imp)},"重点",{rng(res)},0)', ""],
        ["完成率", "=B7/B6", "=C7/C6", "已填写 ÷ 要筛的词数"],
    ]
    table(ws, 6, stats, [16, 12, 14, 52])
    for r in (13,):
        for c in ("B", "C"):
            ws[f"{c}{r}"].number_format = "0%"
    for r in range(6, 14):
        for c in ("B", "C"):
            ws[f"{c}{r}"].alignment = CENTER
    ws["A15"], ws["B15"] = "填写顺序", "操作"
    for c in ("A15", "B15"):
        ws[c].font, ws[c].fill = FB, SUB_FILL
    table(ws, 16, [
        [1, "先读“使用说明”页（约5分钟）。"],
        [2, f"在“筛词表”页筛选“影响”=重点（{n_key}个，两人都筛），先认真判断这些词，尤其看标“（单独出现）”的例句。"],
        [3, f"再快速过完“负责”=仅{who}的{n_mine - n_key}个影响小的词：凭第一印象填，拿不准就填0。标“{other}”的灰色行不用填。"],
        [4, "独立完成，填完前不和对方商量；填完把本文件原样发回B，不改文件名、列名和行序。"],
    ])
    ws.column_dimensions["B"].width = 12
    ws.merge_cells("B16:D16"), ws.merge_cells("B17:D17"), ws.merge_cells("B18:D18"), ws.merge_cells("B19:D19")
    for r in range(16, 20):
        ws.row_dimensions[r].height = 30
        ws[f"A{r}"].alignment = CENTER

    # ---- 使用说明 ----
    ws = wb.create_sheet("使用说明")
    title(ws, "候选词筛选填写说明（规则v0.2 第4步）", "完整口径见《AI技能筛词与标注对齐说明_v0.2》第一、二部分。")
    header(ws, 5, ["填写值", "层级", "意思", "会不会让广告算“要求AI技能”", "例子（现有词）"])
    r = table(ws, 6, [
        [1, "严格", "意思基本唯一，单独出现也指AI", "会，单独出现就算", "深度学习、PyTorch、目标检测、ChatGPT"],
        [2, "条件", "常指AI，但单独出现时也常有别的意思", "会，但同一条广告要有另一个严格词或条件词", "机器视觉（也指工业检测设备）、Midjourney"],
        [3, "宽泛", "只说明和AI有关，说明不了要求AI技能", "不会，只计入宽泛版", "人工智能、AI、CV、Transformer、AI工具"],
        [0, "不加入", "不是AI方法、模型、工具或任务", "—", "Python、SQL、大数据、智能家居、算法、模型"],
    ], [9, 10, 36, 34, 40])
    ws.cell(r + 1, 1, "判断顺序").font = FB
    ws.cell(r + 1, 1).fill = SUB_FILL
    r = table(ws, r + 2, [
        ["①", "这个词本身是不是一种AI方法、模型、工具或任务？", "不是 → 0", "", "参照Acemoglu等（2022）清单：机器学习、神经网络、目标检测"],
        ["②", "例句里，它是不是对求职者的技能要求或岗位工作内容？", "大多不是 → 0", "", "公司介绍、产品名称不算"],
        ["③", "单独出现、旁边没有其他AI词时，是否仍指AI？", "常有别的意思 → 最多选2", "", "看标“（单独出现）”的例句和“单独出现广告数”"],
    ])
    ws.cell(r + 1, 1, "直接填0").font = FB
    ws.cell(r + 1, 1).fill = SUB_FILL
    r = table(ws, r + 2, [
        ["一般编程或数据技能", "Python、SQL、数据分析、pandas、numpy", "", "", ""],
        ["一般IT词", "大数据、云计算、Hadoop、Spark", "", "", ""],
        ["行业产品词", "智能家居、智能硬件", "", "", ""],
        ["过于宽泛的词", "算法、模型、智能、数学、视觉", "", "", ""],
    ])
    ws.cell(r + 1, 1, "各列怎么看").font = FB
    ws.cell(r + 1, 1).fill = SUB_FILL
    r = table(ws, r + 2, [
        ["影响", "重点 = 单独出现≥100条广告。这120个词决定了新增影响的98%，要认真判断；“影响小”的词填什么对结果几乎没有影响", "", "", ""],
        ["负责", "两人 = 重点词，A、B都筛；仅A / 仅B = 影响小的词，按编号顺序交替分配，只由一人筛。不归你负责的行是灰色的，不用填", "", "", ""],
        ["来源组、种子词、相似度", "这个词是由哪个AI词找出来的、在文本中有多像。只是线索，相似度高不等于是AI词", "", "", ""],
        ["广告数", "ChatGPT发布（2022-11-30）前、后分别有多少条广告出现这个词", "", "", ""],
        ["单独出现广告数", "这个词出现、但广告里没有任何现有严格词的条数。加入词典后，真正新增判为AI的就是这些广告", "", "", ""],
        ["共现相关度", "含这个词的广告中同时出现核心AI词的比例。只作参考，可以不同意，不同意时在备注写理由；相关度高的词单独出现时未必指AI", "", "", ""],
        ["例句", "红色加粗【】是候选词。橙色“（单独出现）”= 广告里没有现有严格词；灰色“（有其他AI词）”= 广告别处有现有严格词，不一定在这一句。有35个词的例句会重复（同一广告多次发布）", "", "", ""],
    ])
    for i in range(r - 7, r):
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=5)
        ws.row_dimensions[i].height = 32
    ws.cell(r + 1, 1, "注意事项").font = FB
    ws.cell(r + 1, 1).fill = NOTE_FILL
    table(ws, r + 2, [
        [1, "独立完成，填完前两人不商量、不看对方的表。", "", "", ""],
        [2, "合并规则：重点词两人都填1/2/3 → 加入，层级取更严的；有一人填0 → 不加入。单人负责的词按负责人的结果。", "", "", ""],
        [3, "本文件含招聘广告原文：只用U盘或点对点发送，不传Git、不发群、不放公开网盘。", "", "", ""],
    ])

    # ---- 筛词表 ----
    ws = wb.create_sheet("筛词表")
    ws.sheet_properties.tabColor = "1F4E78"
    title(ws, f"候选词筛选表（{who}）", f"共{n}个候选词，编号顺序与CSV版一致。你负责{n_mine}个（重点{n_key}个＋仅{who}{n_mine - n_key}个）；"
          f"只填“筛选结果”和“备注”两列，灰色行不用填。可用表头筛选“影响”或“负责”。")
    header(ws, HEADER_ROW, [c[0] for c in COLUMNS])
    ws.row_dimensions[HEADER_ROW].height = 44
    for j, (_, width, _, _) in enumerate(COLUMNS, 1):
        ws.column_dimensions[chr(64 + j)].width = width
    for i, row in enumerate(rows):
        rr = FIRST + i
        assigned = who in row["_who"]
        for j, (name, _, get, align) in enumerate(COLUMNS, 1):
            if get is None:
                value = ((f'=IF({res}{rr}="","待填写",IF(ISNUMBER(MATCH(TRIM(TEXT({res}{rr},"0")),{{"0","1","2","3"}},0)),'
                          f'"已填写","取值有误"))') if assigned else f"无需填写（{WHO_ZH[row['_who']]}）")
            else:
                value = get(row)
                if name.startswith("例句"):
                    value = rich_example(value) if assigned else value
            c = ws.cell(rr, j, value)
            c.font, c.alignment, c.border = (F if assigned else FM), align, BORDER
            if not assigned:
                c.fill = GRAY_FILL
            elif name.startswith(("筛选结果", "备注")):
                c.fill = FILL_COL
        ws.cell(rr, COL["相似度"]).number_format = "0.00"
        ws.row_dimensions[rr].height = 96
    ws.freeze_panes = ws.cell(FIRST, COL["来源组"])
    ws.auto_filter.ref = f"A{HEADER_ROW}:{stat}{last}"
    dv = DataValidation(type="list", formula1='"1,2,3,0"', allow_blank=True, showErrorMessage=True,
                        errorTitle="取值有误", error="只能填 1（严格）、2（条件）、3（宽泛）或 0（不加入）",
                        promptTitle="筛选结果", prompt="1严格 2条件 3宽泛 0不加入", showInputMessage=True)
    ws.add_data_validation(dv)
    dv.add(f"{res}{FIRST}:{res}{last}")
    colors = {"1": ("E2EFDA", "375623"), "2": ("DDEBF7", "1F4E78"), "3": ("FFF2CC", "7F6000"), "0": ("F2F2F2", "6B7280")}
    for v, (bg, fg) in colors.items():
        ws.conditional_formatting.add(f"{res}{FIRST}:{res}{last}", FormulaRule(
            formula=[f'AND({res}{FIRST}<>"",TRIM(TEXT({res}{FIRST},"0"))="{v}")'], fill=PatternFill("solid", fgColor=bg),
            font=Font(color=fg, bold=True)))
    for text, fg in (("已填写", "375623"), ("待填写", "7F6000"), ("取值有误", "9C0006")):
        ws.conditional_formatting.add(f"{stat}{FIRST}:{stat}{last}", FormulaRule(
            formula=[f'{stat}{FIRST}="{text}"'], font=Font(color=fg, bold=True)))
    ws.conditional_formatting.add(f"{own}{FIRST}:{own}{last}", FormulaRule(
        formula=[f'{own}{FIRST}="两人"'], font=Font(color="1F4E78", bold=True)))
    ws.conditional_formatting.add(f"{imp}{FIRST}:{imp}{last}", FormulaRule(
        formula=[f'{imp}{FIRST}="重点"'], fill=PatternFill("solid", fgColor="FCE4D6"), font=Font(color="C00000", bold=True)))

    wb.active = 0
    wb.save(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    args = ap.parse_args()
    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    d = Path(storage["analysis_root"]) / "ai_w2v_screening_v0.2"
    for who in ("A", "B"):
        with (d / f"筛词表_{who}.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert [int(r["编号"]) for r in rows] == list(range(1, len(rows) + 1)), "编号必须是1..N且顺序不变"
        assign = assignment(rows)
        for r in rows:
            r["_who"] = assign[r["编号"]]
        out = d / f"筛词表_{who}.xlsx"
        build(rows, who, out)
        print(f"WROTE {out} rows={len(rows)} key={sum(int(r['不含现有严格词的广告数']) >= KEY_MIN_ALONE for r in rows)}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
