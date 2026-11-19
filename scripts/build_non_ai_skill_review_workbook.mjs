import fs from "node:fs/promises";
import { pathToFileURL } from "node:url";


const ARTIFACT_TOOL_ENTRY = String.raw`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1117-835-0_26.1117.835.0_x64__3k8sg7r9htsxt\dependencies\node\node_modules\@oai\artifact-tool\dist\artifact_tool.mjs`;
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(ARTIFACT_TOOL_ENTRY).href);

const PROJECT_ROOT = String.raw`D:\SRTP科研`;
const DATA_PATH = `${PROJECT_ROOT}\\outputs\\qc\\non_ai_skill_unified_review_2022_v0.1.json`;
const OUTPUT_DIR = `${PROJECT_ROOT}\\outputs\\non_ai_skill_review_20261119`;
const OUTPUT_PATH = `${OUTPUT_DIR}\\三类非AI技能人工复核表_2022_v0.1.xlsx`;

const rows = JSON.parse(await fs.readFile(DATA_PATH, "utf8"));
if (rows.length !== 240) throw new Error(`Expected 240 review rows, got ${rows.length}`);
await fs.mkdir(OUTPUT_DIR, { recursive: true });

const workbook = Workbook.create();
const guide = workbook.worksheets.add("填写说明");
const review = workbook.worksheets.add("人工复核");
const results = workbook.worksheets.add("程序结果");

const fontFamily = "Microsoft YaHei";
const colors = {
  navy: "#1F4E78",
  navyLight: "#D9EAF7",
  teal: "#0F766E",
  tealLight: "#E2F0D9",
  gold: "#BF9000",
  goldLight: "#FFF2CC",
  purple: "#7030A0",
  purpleLight: "#E4DFEC",
  gray: "#666666",
  grayLight: "#F2F2F2",
  orange: "#C65911",
  orangeLight: "#FCE4D6",
  red: "#C00000",
  redLight: "#F4CCCC",
  white: "#FFFFFF",
  border: "#D9E2F3",
};

function clean(value) {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") return value;
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
}

function setTitle(sheet, range, title, subtitle, subtitleRange) {
  sheet.mergeCells(range);
  const titleCell = sheet.getRange(range);
  titleCell.values = [[title]];
  titleCell.format = {
    fill: colors.navy,
    font: { name: fontFamily, size: 18, bold: true, color: colors.white },
    verticalAlignment: "center",
  };
  titleCell.format.rowHeight = 34;
  sheet.mergeCells(subtitleRange);
  const subtitleCell = sheet.getRange(subtitleRange);
  subtitleCell.values = [[subtitle]];
  subtitleCell.format = {
    fill: colors.navyLight,
    font: { name: fontFamily, size: 10, color: colors.navy },
    verticalAlignment: "center",
    wrapText: true,
  };
  subtitleCell.format.rowHeight = 28;
}

function sectionHeader(sheet, address, text, endColumn = "H") {
  const row = address.match(/\d+/)[0];
  const range = `${address}:${endColumn}${row}`;
  sheet.mergeCells(range);
  const cell = sheet.getRange(range);
  cell.values = [[text]];
  cell.format = {
    fill: colors.teal,
    font: { name: fontFamily, size: 12, bold: true, color: colors.white },
    verticalAlignment: "center",
  };
  cell.format.rowHeight = 25;
}

// 填写说明
guide.showGridLines = false;
guide.tabColor = colors.navy;
setTitle(
  guide,
  "A2:H2",
  "2022年三类非AI技能人工复核说明",
  "软件技能、认知技能、社交技能统一复核｜先独立人工判断，再查看程序结果",
  "A3:H3",
);

sectionHeader(guide, "A5", "一、判定代码");
guide.getRange("A6:C9").values = [
  ["代码", "含义", "什么时候用"],
  [1, "明确要求该技能", "招聘广告中出现清楚、具体的技能要求或工作任务"],
  [0, "没有要求该技能", "通读岗位名称和职位描述后，没有发现该类要求"],
  [9, "无法判断", "文本过短、语义含糊，或证据相互矛盾，不能可靠下结论"],
];
guide.getRange("A6:C6").format = {
  fill: colors.navy,
  font: { name: fontFamily, bold: true, color: colors.white },
  horizontalAlignment: "center",
};
guide.getRange("A7:A9").format = {
  fill: colors.goldLight,
  font: { name: fontFamily, bold: true, color: colors.navy },
  horizontalAlignment: "center",
};
guide.getRange("A6:C9").format.borders = { preset: "all", style: "thin", color: colors.border };
guide.getRange("B7:C9").format.wrapText = true;

sectionHeader(guide, "A11", "二、三类技能的简明口径");
guide.getRange("A12:C15").values = [
  ["技能", "核心问题", "常见例子"],
  ["软件技能", "岗位是否要求使用具体软件、编程语言、数据库、办公软件或数字化工具？", "Python、Java、SQL、CAD、ERP、Excel、Word、PowerPoint等"],
  ["认知技能", "岗位是否明确要求分析、推理、判断、研究、创新或解决复杂问题？", "数据分析、逻辑判断、独立研究、方案设计、问题解决等"],
  ["社交技能", "岗位是否明确要求与人沟通、协作、谈判、服务、管理或组织协调？", "沟通表达、团队协作、客户维护、谈判、组织协调、领导管理等"],
];
guide.getRange("A12:C12").format = {
  fill: colors.navy,
  font: { name: fontFamily, bold: true, color: colors.white },
  horizontalAlignment: "center",
};
guide.getRange("A13:A15").format = {
  fill: colors.tealLight,
  font: { name: fontFamily, bold: true, color: colors.teal },
};
guide.getRange("A12:C15").format.borders = { preset: "all", style: "thin", color: colors.border };
guide.getRange("A13:C15").format.wrapText = true;

sectionHeader(guide, "A17", "三、复核步骤");
guide.getRange("A18:H21").values = [
  ["1", "先看“人工复核”工作表，只阅读岗位名称和职位描述。不要提前打开“程序结果”。", "", "", "", "", "", ""],
  ["2", "按“分配给”列填写：A填黄色区域，B填蓝色区域；双人样本必须独立判断，不能先讨论。", "", "", "", "", "", ""],
  ["3", "软件、认知、社交三列都要填1/0/9。拿不准时选9，并在备注中写清原因。", "", "", "", "", "", ""],
  ["4", "两人完成后，再打开“程序结果”对照程序识别。双人意见不一致的样本进入裁决。", "", "", "", "", "", ""],
];
for (let r = 18; r <= 21; r += 1) {
  guide.mergeCells(`B${r}:H${r}`);
}
guide.getRange("A18:A21").format = {
  fill: colors.goldLight,
  font: { name: fontFamily, size: 12, bold: true, color: colors.navy },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
guide.getRange("B18:H21").format = {
  font: { name: fontFamily, size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
guide.getRange("A18:H21").format.borders = { preset: "all", style: "thin", color: colors.border };
guide.getRange("A18:H21").format.rowHeight = 34;

sectionHeader(guide, "A23", "四、分工与完成进度");
guide.getRange("A24:E27").values = [
  ["对象", "需复核", "已完成", "剩余", "完成率"],
  ["复核员A", 150, "", "", ""],
  ["复核员B", 150, "", "", ""],
  ["双人样本（两人均完成）", 60, "", "", ""],
];
guide.getRange("C25").formulas = [[`=COUNTIF('人工复核'!$P$6:$P$245,"已完成")`]];
guide.getRange("C26").formulas = [[`=COUNTIF('人工复核'!$Q$6:$Q$245,"已完成")`]];
guide.getRange("C27").formulas = [[`=COUNTIFS('人工复核'!$F$6:$F$245,"双人独立复核",'人工复核'!$P$6:$P$245,"已完成",'人工复核'!$Q$6:$Q$245,"已完成")`]];
guide.getRange("D25").formulas = [["=B25-C25"]];
guide.getRange("D25:D27").fillDown();
guide.getRange("E25").formulas = [["=C25/B25"]];
guide.getRange("E25:E27").fillDown();
guide.getRange("E25:E27").format.numberFormat = "0.0%";
guide.getRange("A24:E24").format = {
  fill: colors.navy,
  font: { name: fontFamily, bold: true, color: colors.white },
  horizontalAlignment: "center",
};
guide.getRange("A25:A27").format.font = { name: fontFamily, bold: true, color: colors.navy };
guide.getRange("A24:E27").format.borders = { preset: "all", style: "thin", color: colors.border };
guide.getRange("B25:E27").format.horizontalAlignment = "center";

guide.mergeCells("A29:H30");
guide.getRange("A29:H30").values = [["重要：程序给出的0/1只是待检验结果，不是标准答案。人工复核的作用，是发现误判、漏判和规则边界问题，为下一轮修改词典与识别规则提供依据。"]];
guide.getRange("A29:H30").format = {
  fill: colors.redLight,
  font: { name: fontFamily, size: 11, bold: true, color: colors.red },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "medium", color: colors.red },
};
guide.getRange("A29:H30").format.rowHeight = 30;
guide.getRange("A1:H30").format.font.name = fontFamily;
guide.getRange("A1:H30").format.verticalAlignment = "center";
guide.getRange("A:A").format.columnWidth = 27;
guide.getRange("B:B").format.columnWidth = 30;
guide.getRange("C:C").format.columnWidth = 58;
guide.getRange("D:E").format.columnWidth = 13;
guide.getRange("F:H").format.columnWidth = 12;
guide.freezePanes.freezeRows(3);

// 人工复核
review.showGridLines = false;
review.tabColor = colors.gold;
setTitle(
  review,
  "A2:Q2",
  "人工复核｜2022年统一样本（240条）",
  "只根据岗位文本独立判断；A填写黄色区域，B填写蓝色区域。1=明确要求，0=没有要求，9=无法判断。",
  "A3:Q3",
);
const reviewHeaders = [
  "样本编号", "来源记录ID", "平台", "招聘岗位", "职位描述", "复核方式", "分配给",
  "A_软件", "A_认知", "A_社交", "A_备注",
  "B_软件", "B_认知", "B_社交", "B_备注", "A完成状态", "B完成状态",
];
review.getRange("A5:Q5").values = [reviewHeaders];
const reviewValues = rows.map((r) => [
  r.sample_no, clean(r.source_record_id), clean(r.platform), clean(r.job_title), clean(r.job_description),
  clean(r.review_mode), clean(r.assigned_reviewer), "", "", "", "", "", "", "", "", "", "",
]);
review.getRange("A6:Q245").values = reviewValues;
review.getRange("P6").formulasR1C1 = [[`=IF(OR(RC[-9]="A",RC[-9]="A+B"),IF(AND(RC[-8]<>"",RC[-7]<>"",RC[-6]<>""),"已完成","待填写"),"不适用")`]];
review.getRange("P6:P245").fillDown();
review.getRange("Q6").formulasR1C1 = [[`=IF(OR(RC[-10]="B",RC[-10]="A+B"),IF(AND(RC[-5]<>"",RC[-4]<>"",RC[-3]<>""),"已完成","待填写"),"不适用")`]];
review.getRange("Q6:Q245").fillDown();
const reviewTable = review.tables.add("A5:Q245", true, "ManualReviewTable");
reviewTable.style = "TableStyleMedium2";
reviewTable.showFilterButton = true;
review.getRange("A5:G5").format = { fill: colors.navy, font: { name: fontFamily, bold: true, color: colors.white } };
review.getRange("H5:K5").format = { fill: colors.gold, font: { name: fontFamily, bold: true, color: colors.white } };
review.getRange("L5:O5").format = { fill: colors.teal, font: { name: fontFamily, bold: true, color: colors.white } };
review.getRange("P5:Q5").format = { fill: colors.gray, font: { name: fontFamily, bold: true, color: colors.white } };
review.getRange("H6:K245").format.fill = colors.goldLight;
review.getRange("L6:O245").format.fill = colors.navyLight;
review.getRange("P6:Q245").format.fill = colors.grayLight;
review.getRange("H6:J245").dataValidation = { rule: { type: "list", values: ["0", "1", "9"] } };
review.getRange("L6:N245").dataValidation = { rule: { type: "list", values: ["0", "1", "9"] } };
review.getRange("A5:Q245").format.font.name = fontFamily;
review.getRange("A5:Q245").format.verticalAlignment = "center";
review.getRange("A5:Q245").format.borders = { preset: "all", style: "thin", color: "#E7E6E6" };
review.getRange("D6:E245").format.wrapText = true;
review.getRange("K6:O245").format.wrapText = true;
review.getRange("A6:D245").format.rowHeight = 66;
review.getRange("E6:Q245").format.rowHeight = 66;
review.getRange("A5:Q5").format.rowHeight = 34;
review.getRange("A:A").format.columnWidth = 10;
review.getRange("B:B").format.columnWidth = 20;
review.getRange("C:C").format.columnWidth = 10;
review.getRange("D:D").format.columnWidth = 24;
review.getRange("E:E").format.columnWidth = 72;
review.getRange("F:F").format.columnWidth = 15;
review.getRange("G:G").format.columnWidth = 10;
review.getRange("H:J").format.columnWidth = 10;
review.getRange("K:K").format.columnWidth = 25;
review.getRange("L:N").format.columnWidth = 10;
review.getRange("O:O").format.columnWidth = 25;
review.getRange("P:Q").format.columnWidth = 13;
review.freezePanes.freezeRows(5);
review.freezePanes.freezeColumns(4);

// 程序结果与裁决
results.showGridLines = false;
results.tabColor = colors.red;
setTitle(
  results,
  "A2:AB2",
  "程序结果与复核裁决",
  "警告：A、B完成独立人工复核前不要打开本表；程序结果用于发现规则问题，不是标准答案。",
  "A3:AB3",
);
results.getRange("A3:AB3").format = {
  fill: colors.redLight,
  font: { name: fontFamily, size: 11, bold: true, color: colors.red },
  wrapText: true,
  verticalAlignment: "center",
};
const resultHeaders = [
  "样本编号", "来源记录ID", "平台", "招聘岗位", "抽样层",
  "程序_软件", "办公软件", "专业软件", "条件词命中", "软件规则", "软件证据",
  "程序_认知", "认知规则", "认知证据", "程序_社交", "社交规则", "社交证据",
  "A_软件", "B_软件", "A_认知", "B_认知", "A_社交", "B_社交", "是否需裁决",
  "最终_软件", "最终_认知", "最终_社交", "裁决备注",
];
results.getRange("A5:AB5").values = [resultHeaders];
const resultValues = rows.map((r) => [
  r.sample_no, clean(r.source_record_id), clean(r.platform), clean(r.job_title), clean(r.review_stratum),
  r.skill_software, r.software_office_basic, r.software_professional, r.software_has_conditional,
  clean(r.software_rule_ids), clean(r.software_evidence), r.skill_cognitive,
  clean(r.cognitive_rule_id), clean(r.cognitive_evidence), r.skill_social,
  clean(r.social_rule_id), clean(r.social_evidence), "", "", "", "", "", "", "", "", "", "", "",
]);
results.getRange("A6:AB245").values = resultValues;
const linkFormulas = rows.map((_, index) => {
  const row = index + 6;
  return [
    `=IF('人工复核'!H${row}="","",'人工复核'!H${row})`,
    `=IF('人工复核'!L${row}="","",'人工复核'!L${row})`,
    `=IF('人工复核'!I${row}="","",'人工复核'!I${row})`,
    `=IF('人工复核'!M${row}="","",'人工复核'!M${row})`,
    `=IF('人工复核'!J${row}="","",'人工复核'!J${row})`,
    `=IF('人工复核'!N${row}="","",'人工复核'!N${row})`,
  ];
});
results.getRange("R6:W245").formulas = linkFormulas;
const adjudicationFormulas = rows.map((_, index) => {
  const row = index + 6;
  return [`=IF(OR(AND(R${row}<>"",S${row}<>"",R${row}<>S${row}),AND(T${row}<>"",U${row}<>"",T${row}<>U${row}),AND(V${row}<>"",W${row}<>"",V${row}<>W${row})),"是","否")`];
});
results.getRange("X6:X245").formulas = adjudicationFormulas;
const resultTable = results.tables.add("A5:AB245", true, "ProgramResultsTable");
resultTable.style = "TableStyleMedium2";
resultTable.showFilterButton = true;
results.getRange("A5:E5").format = { fill: colors.navy, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("F5:K5").format = { fill: colors.navy, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("L5:N5").format = { fill: colors.purple, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("O5:Q5").format = { fill: colors.teal, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("R5:X5").format = { fill: colors.gray, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("Y5:AB5").format = { fill: colors.orange, font: { name: fontFamily, bold: true, color: colors.white } };
results.getRange("F6:Q245").format.fill = colors.navyLight;
results.getRange("R6:X245").format.fill = colors.grayLight;
results.getRange("Y6:AB245").format.fill = colors.orangeLight;
results.getRange("Y6:AA245").dataValidation = { rule: { type: "list", values: ["0", "1", "9"] } };
results.getRange("A5:AB245").format.font.name = fontFamily;
results.getRange("A5:AB245").format.verticalAlignment = "center";
results.getRange("A5:AB245").format.borders = { preset: "all", style: "thin", color: "#E7E6E6" };
results.getRange("D6:Q245").format.wrapText = true;
results.getRange("AB6:AB245").format.wrapText = true;
results.getRange("A5:AB5").format.rowHeight = 34;
results.getRange("A6:AB245").format.rowHeight = 58;
results.getRange("A:A").format.columnWidth = 10;
results.getRange("B:B").format.columnWidth = 20;
results.getRange("C:C").format.columnWidth = 10;
results.getRange("D:D").format.columnWidth = 24;
results.getRange("E:E").format.columnWidth = 20;
results.getRange("F:I").format.columnWidth = 11;
results.getRange("J:J").format.columnWidth = 24;
results.getRange("K:K").format.columnWidth = 50;
results.getRange("L:L").format.columnWidth = 11;
results.getRange("M:M").format.columnWidth = 14;
results.getRange("N:N").format.columnWidth = 45;
results.getRange("O:O").format.columnWidth = 11;
results.getRange("P:P").format.columnWidth = 14;
results.getRange("Q:Q").format.columnWidth = 45;
results.getRange("R:W").format.columnWidth = 10;
results.getRange("X:X").format.columnWidth = 13;
results.getRange("Y:AA").format.columnWidth = 11;
results.getRange("AB:AB").format.columnWidth = 28;
results.freezePanes.freezeRows(5);
results.freezePanes.freezeColumns(4);

workbook.recalculate();

const inspection = await workbook.inspect({
  kind: "workbook,sheet,table,formula",
  maxChars: 10000,
  tableMaxRows: 4,
  tableMaxCols: 8,
  options: { maxResults: 100 },
});
await fs.writeFile(`${OUTPUT_DIR}\\workbook_inspection.ndjson`, inspection.ndjson ?? String(inspection), "utf8");

const formulaCheck = {
  guide: guide.getRange("A24:E27").formulaInfos,
  review: review.getRange("P5:Q10").formulaInfos,
  results: results.getRange("R5:X10").formulaInfos,
};
await fs.writeFile(`${OUTPUT_DIR}\\formula_check.json`, JSON.stringify(formulaCheck, null, 2), "utf8");

for (const [sheetName, fileName, scale] of [
  ["填写说明", "preview_填写说明.png", 1],
  ["人工复核", "preview_人工复核.png", 0.35],
  ["程序结果", "preview_程序结果.png", 0.3],
]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale, format: "png" });
  await fs.writeFile(`${OUTPUT_DIR}\\${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT_PATH);

console.log(JSON.stringify({ output: OUTPUT_PATH, rows: rows.length, sheets: ["填写说明", "人工复核", "程序结果"] }, null, 2));
