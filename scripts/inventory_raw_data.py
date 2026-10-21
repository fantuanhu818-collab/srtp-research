"""只读盘点原始招聘数据（CSV / DTA）。

严格只读：不修改、不移动、不重命名、不删除原始目录中的任何文件。
本脚本只读取原始文件元信息（大小、修改时间）与 CSV 的头部/小样本，
并对 2018—2025 年的 CSV 做只读解析检查（编码、分隔符、字段、引号换行、稳定广告 ID）。

所有小型审计结果写入项目目录；原始数据始终只读。
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- 常量
PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
RAW_ROOT = Path(os.environ.get("SRTP_RAW_ROOT", r"D:\SRTP\分年份保存数据"))

STUDY_MIN = 2018
STUDY_MAX = 2025

OUT_SOURCE_FILES = PROJECT_ROOT / "outputs" / "qc" / "source_files.csv"
OUT_INVENTORY = PROJECT_ROOT / "outputs" / "qc" / "raw_inventory.csv"
OUT_SCHEMA_REPORT = PROJECT_ROOT / "outputs" / "qc" / "raw_schema_report.md"
OUT_LOG = PROJECT_ROOT / "logs" / "raw_inventory.log"

ENCODING_HINT_BYTES = 65536          # 用于编码/分隔符/表头探测的原始字节数
CSV_SAMPLE_ROWS = 2000               # 每个候选年份 CSV 采样的逻辑记录数
CSV_SAMPLE_VALUES = 5                # 保留的样本值上限（仅用于统计，不打印）

YEAR_RE = re.compile(r"(19|20)\d{2}")

# 用于识别疑似“稳定广告 ID”列的字段名模式
ID_NAME_RE = re.compile(
    r"(^\s*(id|编号|序号|代码|广告|职位号|招聘号|recruit\s*id|job\s*id|post\s*id|ad\s*id)\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- 日志
class Logger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w", encoding="utf-8")

    def log(self, msg: str) -> None:
        line = f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


log = Logger(OUT_LOG)


# ---------------------------------------------------------------- 编码/分隔符探测
def detect_encoding(raw: bytes):
    """返回 (encoding, bom_description)。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", "UTF-8 BOM"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le", "UTF-16 LE BOM"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be", "UTF-16 BE BOM"
    try:
        raw.decode("utf-8")
        return "utf-8", "UTF-8 (无 BOM)"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gb18030")
        return "gb18030", "GB18030 (中文)"
    except UnicodeDecodeError:
        pass
    return "latin-1", "latin-1 (回退，无法确定)"


def detect_delimiter(header_text: str) -> str:
    counts = {ch: header_text.count(ch) for ch in (",", "\t", ";", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_head_raw(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(ENCODING_HINT_BYTES)


def first_header_line(path: Path, encoding: str) -> str:
    with open(path, "r", encoding=encoding, newline="", errors="replace") as f:
        return f.readline()


# ---------------------------------------------------------------- CSV 只读解析检查
def csv_schema_check(path: Path, encoding: str, delimiter: str):
    """对单个 CSV 做只读解析检查，返回结果字典。"""
    result = {
        "encoding": encoding,
        "delimiter": delimiter,
        "field_names": None,
        "n_fields": None,
        "parse_ok": False,
        "parse_error": None,
        "n_rows_sampled": 0,
        "field_count_distribution": Counter(),
        "has_quoted_newline": False,
        "id_candidate_columns": [],
        "any_all_unique_nonnull_col": False,
    }

    field_names = None
    n_rows = 0
    has_newline = False
    field_len_counter = Counter()
    sample_rows = []
    all_unique_cols = set()
    candidate_nonnull = set()
    candidate_unique = set()
    # 首轮遍历：统计字段数分布、检测引号换行、记录样本
    with open(path, "r", encoding=encoding, newline="", errors="replace") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for i, row in enumerate(reader):
            if i == 0:
                field_names = row
                field_len_counter[len(row)] += 1
                continue
            n_rows += 1
            field_len_counter[len(row)] += 1
            if any("\n" in c or "\r" in c for c in row):
                has_newline = True
            if len(sample_rows) < CSV_SAMPLE_ROWS:
                sample_rows.append(row)
            if n_rows >= CSV_SAMPLE_ROWS:
                break

    result["field_names"] = field_names
    result["n_fields"] = len(field_names) if field_names is not None else None
    result["n_rows_sampled"] = n_rows
    result["field_count_distribution"] = field_len_counter
    result["has_quoted_newline"] = has_newline

    # 判断解析是否正常：表头字段数 == 各数据行字段数（且行数 > 0）
    if field_names is None:
        result["parse_ok"] = False
        result["parse_error"] = "无法读取表头"
    elif len(field_len_counter) == 1:
        result["parse_ok"] = True
    else:
        result["parse_ok"] = False
        result["parse_error"] = f"字段数不一致: {dict(field_len_counter)}"

    # 稳定广告 ID 启发式检查
    if field_names:
        for idx, name in enumerate(field_names):
            if ID_NAME_RE.search(name or ""):
                result["id_candidate_columns"].append(name)
        # 对样本中的每一列统计非空唯一性
        n_cols = len(field_names)
        col_nonnull = [True] * n_cols
        col_values = [set() for _ in range(n_cols)]
        for row in sample_rows:
            for c in range(n_cols):
                v = row[c] if c < len(row) else ""
                if v in ("", None):
                    col_nonnull[c] = False
                else:
                    col_values[c].add(v)
        for c in range(n_cols):
            # 样本内全非空且全唯一 → 可能是事实 ID
            if col_nonnull[c] and len(col_values[c]) == len(sample_rows):
                all_unique_cols.add(field_names[c])
    result["any_all_unique_nonnull_col"] = bool(all_unique_cols)
    result["all_unique_nonnull_cols"] = sorted(all_unique_cols)

    return result


# ---------------------------------------------------------------- 主流程
def main() -> int:
    log.log("=== 开始原始数据只读盘点 ===")
    log.log(f"原始目录: {RAW_ROOT}")

    if not RAW_ROOT.is_dir():
        log.log(f"FATAL: 原始目录不存在或不可读: {RAW_ROOT}")
        return 1

    files = sorted(
        p for p in RAW_ROOT.iterdir()
        if p.is_file() and p.suffix.lower() in (".csv", ".dta")
    )
    log.log(f"发现 {len(files)} 个 CSV/DTA 文件")

    records = []
    for p in files:
        m = YEAR_RE.search(p.stem)
        year = int(m.group(0)) if m else -1
        fmt = p.suffix.lower().lstrip(".")
        st = p.stat()
        in_window = STUDY_MIN <= year <= STUDY_MAX
        suggested_use = "primary_candidate" if fmt == "csv" else "reference_only"
        # 稳定逻辑 ID：CSV 为主数据，DTA 为参考
        if fmt == "csv":
            source_file_id = f"jobs_{year}"
        else:
            source_file_id = f"jobs_{year}_dta"
        records.append(
            {
                "source_file_id": source_file_id,
                "filename": p.name,
                "absolute_path": str(p),
                "year": year,
                "format": fmt,
                "size_bytes": st.st_size,
                "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(sep=" ", timespec="seconds"),
                "in_study_window": in_window,
                "suggested_use": suggested_use,
            }
        )

    # ---------------- 写 source_files.csv
    OUT_SOURCE_FILES.parent.mkdir(parents=True, exist_ok=True)
    src_fields = [
        "source_file_id", "filename", "absolute_path", "year", "format",
        "size_bytes", "mtime", "in_study_window", "suggested_use",
    ]
    with open(OUT_SOURCE_FILES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=src_fields)
        w.writeheader()
        for r in records:
            w.writerow(r)
    log.log(f"写入 {OUT_SOURCE_FILES}")

    # ---------------- 写 raw_inventory.csv
    OUT_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    inv_fields = [
        "filename", "absolute_path", "year", "format",
        "size_bytes", "mtime", "in_study_window", "suggested_use", "source_file_id",
    ]
    with open(OUT_INVENTORY, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=inv_fields)
        w.writeheader()
        for r in records:
            w.writerow({k: r[k] for k in inv_fields})
    log.log(f"写入 {OUT_INVENTORY}")

    # ---------------- 2018—2025 CSV 只读解析检查
    candidate_csvs = [r for r in records if r["format"] == "csv" and r["in_study_window"]]
    schema_results = {}  # year -> result dict
    for r in sorted(candidate_csvs, key=lambda x: x["year"]):
        path = Path(r["absolute_path"])
        log.log(f"检查 CSV {path.name} ...")
        try:
            raw = read_head_raw(path)
            encoding, bom = detect_encoding(raw)
            header_text = first_header_line(path, encoding)
            delimiter = detect_delimiter(header_text)
            res = csv_schema_check(path, encoding, delimiter)
            res["bom"] = bom
            res["delimiter"] = delimiter
            res["encoding"] = encoding
            schema_results[r["year"]] = res
            log.log(
                f"  {path.name}: encoding={encoding}({bom}) delimiter={repr(delimiter)} "
                f"n_fields={res['n_fields']} parse_ok={res['parse_ok']} "
                f"quoted_newline={res['has_quoted_newline']} "
                f"id_candidates={res['id_candidate_columns']}"
            )
        except Exception as exc:  # noqa: BLE001 —— 记录异常，不中断
            schema_results[r["year"]] = {
                "encoding": None, "delimiter": None, "field_names": None,
                "n_fields": None, "parse_ok": False, "parse_error": repr(exc),
                "n_rows_sampled": 0, "field_count_distribution": Counter(),
                "has_quoted_newline": None, "id_candidate_columns": [],
                "any_all_unique_nonnull_col": None, "all_unique_nonnull_cols": [],
                "bom": None,
            }
            log.log(f"  {path.name}: 解析异常 -> {exc!r}")

    # ---------------- 跨年份字段一致性
    field_name_sets = {
        y: res["field_names"]
        for y, res in schema_results.items()
        if res.get("field_names") is not None
    }
    if field_name_sets:
        baseline = next(iter(field_name_sets.values()))
        identical = all(v == baseline for v in field_name_sets.values())
    else:
        identical = None

    # ---------------- 写 raw_schema_report.md
    OUT_SCHEMA_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SCHEMA_REPORT, "w", encoding="utf-8") as f:
        f.write("# 原始数据只读盘点 —— CSV Schema 报告\n\n")
        f.write(f"> 生成时间：{dt.datetime.now().isoformat(sep=' ', timespec='seconds')}\n")
        f.write(f"> 原始目录：`{RAW_ROOT}`（严格只读，未改动任何文件）\n\n")

        f.write("## 1. 文件概览\n\n")
        f.write("| 年份 | 格式 | 大小 (字节) | 修改时间 | 候选研究年 | 建议用途 |\n")
        f.write("|---|---|---:|---|---|---|\n")
        for r in sorted(records, key=lambda x: x["year"]):
            f.write(
                f"| {r['year']} | {r['format'].upper()} | {r['size_bytes']} | "
                f"{r['mtime']} | {'是' if r['in_study_window'] else '否'} | "
                f"{r['suggested_use']} |\n"
            )
        n_csv = sum(1 for r in records if r["format"] == "csv")
        n_dta = sum(1 for r in records if r["format"] == "dta")
        f.write(f"\n- CSV 文件数：{n_csv}\n")
        f.write(f"- DTA 文件数：{n_dta}\n\n")

        f.write("## 2. 2018—2025 年 CSV 解析检查\n\n")
        f.write("（字段值为占位统计，不打印任何岗位描述、企业名称、电话或邮箱。）\n\n")
        for year in sorted(schema_results):
            res = schema_results[year]
            f.write(f"### {year}\n\n")
            f.write(f"- 编码：`{res.get('encoding')}`（{res.get('bom')}）\n")
            f.write(f"- 分隔符：`{repr(res.get('delimiter'))}`\n")
            f.write(f"- 字段数量：`{res.get('n_fields')}`\n")
            f.write(f"- 能否正确解析：`{'是' if res.get('parse_ok') else '否'}`"
                    + (f"（{res.get('parse_error')}）" if res.get("parse_error") else "") + "\n")
            f.write(f"- 采样逻辑记录数：`{res.get('n_rows_sampled')}`\n")
            f.write(f"- 是否存在引号包围的换行：`{'是' if res.get('has_quoted_newline') else '否'}`\n")
            f.write(f"- 疑似 ID 列（按字段名）：`{res.get('id_candidate_columns')}`\n")
            f.write(f"- 样本内全非空且全唯一的列（弱信号，多为长文本/日期，非稳定 ID）：`{res.get('all_unique_nonnull_cols')}`\n")
            fn = res.get("field_names")
            if fn:
                f.write("- 字段名称（" + str(len(fn)) + " 个）：\n\n")
                for i, name in enumerate(fn, 1):
                    f.write(f"  {i}. `{name}`\n")
            f.write("\n")

        f.write("## 3. 跨年份字段一致性\n\n")
        if identical is True:
            f.write("各候选年份 CSV 的字段名称与顺序**完全一致**。\n\n")
        elif identical is False:
            f.write("各候选年份 CSV 的字段名称/顺序**不完全一致**，需在清洗前统一。\n\n")
            for y in sorted(field_name_sets):
                f.write(f"- {y}: {len(field_name_sets[y])} 个字段\n")
        else:
            f.write("未能获得字段信息，无法判断一致性。\n\n")

        f.write("## 4. 说明\n\n")
        f.write("- 本报告为**只读盘点**，未清洗、未生成 Parquet、未运行 2022 年垂直切片。\n")
        f.write("- 行数与 SHA-256 校验未在本轮计算（属后续步骤）。\n")
        f.write("- CSV 标记为 `primary_candidate`，DTA 标记为 `reference_only`，未做拼接。\n")

    log.log(f"写入 {OUT_SCHEMA_REPORT}")

    log.log("=== 只读盘点完成 ===")
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
