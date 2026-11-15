import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";


const moduleRoot = process.env.CODEX_NODE_MODULES;
if (!moduleRoot) {
  throw new Error("缺少CODEX_NODE_MODULES环境变量");
}
const artifactModule = path.join(moduleRoot, "@oai", "artifact-tool", "dist", "artifact_tool.mjs");
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(artifactModule).href);

const projectRoot = process.env.SRTP_PROJECT_ROOT || "D:/SRTP科研";
const outputPath = path.join(projectRoot, "outputs", "qc", "cleaning_v1_report.xlsx");
const previewRoot = path.join(projectRoot, "outputs", "qc", "cleaning_v1_previews");

async function csvValues(filename, sheetName) {
  const text = (await fs.readFile(path.join(projectRoot, "outputs", "qc", filename), "utf8"))
    .replace(/^\uFEFF/, "");
  const imported = await Workbook.fromCSV(text, { sheetName });
  return imported.worksheets.getItem(sheetName).getUsedRange(true).values;
}

const summaryCsv = await csvValues("cleaning_v1_summary.csv", "summary_source");
const rulesCsv = await csvValues("cleaning_v1_actions.csv", "rules_source");
const examplesCsv = await csvValues("cleaning_v1_examples.csv", "examples_source");
const workbook = Workbook.create();
const readme = workbook.worksheets.add("使用说明");
const summary = workbook.worksheets.add("清洗汇总");
const rules = workbook.worksheets.add("处理规则");
const examples = workbook.worksheets.add("前后对照切片");
const fontFamily = "Arial";
const darkBlue = "#1F4E78";
const lightBlue = "#D9EAF7";
const lightAmber = "#FFF2CC";
const lightRed = "#FCE4D6";
const bodyText = "#222222";

for (const sheet of [readme, summary, rules, examples]) {
  sheet.showGridLines = false;
  sheet.getRange("A1:Z100").format.font = { name: fontFamily, size: 10, color: bodyText };
}

readme.getRange("A2:F2").merge();
readme.getRange("A2").values = [["SRTP招聘数据清洗 v1"]];
readme.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: darkBlue };
readme.getRange("A4:B10").values = [
  ["项目", "说明"],
  ["数据范围", "2018—2025年上市公司招聘数据"],
  ["输入", "23个正式字段的标准化数据，共6,050,088条"],
  ["输出", "清洗后保留5,235,461条；删除814,627条"],
  ["工资使用建议", "后续分析优先使用“月薪代表值”：两个端点有效时取均值，单端点有效时取该值"],
  ["追溯方式", "用“来源记录ID”定位原记录；交换、缺失和重复均有独立标记"],
  ["删除证据", "被删除记录另存证据表，并记录删除原因"],
];
readme.getRange("A4:B4").format = { fill: darkBlue, font: { name: fontFamily, bold: true, color: "#FFFFFF" } };
readme.getRange("A5:A10").format = { fill: lightBlue, font: { name: fontFamily, bold: true } };
readme.getRange("A4:B10").format.verticalAlignment = "center";
readme.getRange("A4:B10").format.borders = { preset: "outside", style: "thin", color: "#B4C7E7" };
readme.getRange("A:A").format.columnWidth = 20;
readme.getRange("B:B").format.columnWidth = 86;
readme.getRange("B5:B10").format.wrapText = true;
readme.getRange("A4:B10").format.autofitRows();
readme.tabColor = darkBlue;

summary.getRange("A2:J2").merge();
summary.getRange("A2").values = [["2018—2025年清洗数量汇总"]];
summary.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: darkBlue };
const summaryHeaders = ["年份", "输入记录", "删除：工资无效", "删除：重复", "清洗后记录", "工资交换", "日期交换", "单工资端点", "学历缺失（保留）", "结束日期缺失（保留）"];
const summaryRows = summaryCsv.slice(1, 9).map((row) => row.map((value, index) => index === 0 ? Number(value) : Number(value)));
summary.getRange("A4:J12").values = [summaryHeaders, ...summaryRows];
summary.getRange("A13").values = [["合计"]];
summary.getRange("B13:J13").formulas = [[
  "=SUM(B5:B12)", "=SUM(C5:C12)", "=SUM(D5:D12)", "=SUM(E5:E12)", "=SUM(F5:F12)",
  "=SUM(G5:G12)", "=SUM(H5:H12)", "=SUM(I5:I12)", "=SUM(J5:J12)"
]];
summary.getRange("A4:J4").format = { fill: darkBlue, font: { name: fontFamily, bold: true, color: "#FFFFFF" } };
summary.getRange("A13:J13").format = { fill: lightBlue, font: { name: fontFamily, bold: true } };
summary.getRange("B5:J13").format.numberFormat = "#,##0";
summary.getRange("A4:J13").format.verticalAlignment = "center";
summary.getRange("A4:J13").format.borders = { preset: "outside", style: "thin", color: "#B4C7E7" };
summary.getRange("A:A").format.columnWidth = 11;
summary.getRange("B:J").format.columnWidth = 18;
summary.freezePanes.freezeRows(4);
summary.tabColor = darkBlue;

rules.getRange("A2:D2").merge();
rules.getRange("A2").values = [["已确认的数据清洗规则"]];
rules.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: darkBlue };
const rulesHeaders = ["问题", "判断规则", "处理动作", "可追溯字段"];
const rulesRows = rulesCsv.slice(1).map((row) => [row[0], row[1], row[2], row[3]]);
rules.getRange(`A4:D${4 + rulesRows.length}`).values = [rulesHeaders, ...rulesRows];
rules.getRange("A4:D4").format = { fill: darkBlue, font: { name: fontFamily, bold: true, color: "#FFFFFF" } };
rules.getRange(`A5:D${4 + rulesRows.length}`).format.wrapText = true;
rules.getRange(`A4:D${4 + rulesRows.length}`).format.verticalAlignment = "center";
rules.getRange(`A4:D${4 + rulesRows.length}`).format.borders = { preset: "outside", style: "thin", color: "#B4C7E7" };
rules.getRange("A:A").format.columnWidth = 26;
rules.getRange("B:B").format.columnWidth = 42;
rules.getRange("C:C").format.columnWidth = 38;
rules.getRange("D:D").format.columnWidth = 32;
rules.getRange(`A5:D${4 + rulesRows.length}`).format.autofitRows();
rules.freezePanes.freezeRows(4);
rules.tabColor = "#5B9BD5";

examples.getRange("A2:S2").merge();
examples.getRange("A2").values = [["典型记录：清洗前后对照（每类3条）"]];
examples.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: darkBlue };
const exampleHeaders = ["问题", "处理动作", "来源记录ID", "企业名称", "招聘岗位", "工作城市", "最低月薪_原始", "最高月薪_原始", "最低月薪_清洗后", "最高月薪_清洗后", "月薪代表值", "发布日期_原始", "结束日期_原始", "发布日期_清洗后", "结束日期_清洗后", "学历_原始", "学历_清洗后", "重复组记录数", "保留记录ID"];
const exampleRows = examplesCsv.slice(1).map((row) => row.slice(0, 19));
examples.getRange(`A4:S${4 + exampleRows.length}`).values = [exampleHeaders, ...exampleRows];
examples.getRange("A4:S4").format = { fill: darkBlue, font: { name: fontFamily, bold: true, color: "#FFFFFF" } };
examples.getRange(`A5:S${4 + exampleRows.length}`).format.verticalAlignment = "center";
examples.getRange(`A4:S${4 + exampleRows.length}`).format.borders = { preset: "outside", style: "thin", color: "#D9E2F3" };
examples.getRange(`B5:B${4 + exampleRows.length}`).conditionalFormats.add("containsText", { text: "删除", format: { fill: lightRed, font: { color: "#9C0006", bold: true } } });
examples.getRange(`A5:A${4 + exampleRows.length}`).conditionalFormats.add("containsText", { text: "缺失", format: { fill: lightAmber } });
for (const col of ["A", "B", "C", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S"]) {
  examples.getRange(`${col}:${col}`).format.columnWidth = 20;
}
examples.getRange("D:D").format.columnWidth = 34;
examples.getRange("E:E").format.columnWidth = 30;
examples.getRange(`D5:E${4 + exampleRows.length}`).format.wrapText = true;
examples.freezePanes.freezeRows(4);
examples.freezePanes.freezeColumns(3);
examples.tabColor = "#A5A5A5";

workbook.recalculate();
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewRoot, { recursive: true });
for (const sheetName of ["使用说明", "清洗汇总", "前后对照切片"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewRoot, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const inspection = await workbook.inspect({ kind: "sheet,region,formula", maxChars: 6000, tableMaxRows: 5, tableMaxCols: 8 });
console.log(inspection.ndjson || inspection);
const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  maxChars: 3000,
});
console.log(errorScan.ndjson || errorScan);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`WORKBOOK_OUTPUT=${outputPath}`);
