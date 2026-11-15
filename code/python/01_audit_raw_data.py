"""2018—2025 年招聘原始数据全量只读审计。

目标
----
1. 为后续数据清洗提供可直接使用的年度统计、问题清单和字段信息。
2. 为两名科研初学者提供容易理解的中文报告和术语解释。
3. 保持原始数据严格只读；所有结果写入 Git 仓库的 ``outputs/qc/full_audit``。

审计边界
--------
- CSV 是后续清洗的主输入，因此对 CSV 做全量逐块扫描。
- DTA 是交叉核验文件，只读取元数据（观测数、变量名、存储类型），不做全量复制。
- 本程序只统计问题，不删除、修改或覆盖任何原始记录。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from pandas.io.stata import StataReader


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
RAW_ROOT = Path(os.environ.get("SRTP_RAW_ROOT", r"D:\SRTP\分年份保存数据"))
OUT_ROOT = PROJECT_ROOT / "outputs" / "qc" / "full_audit"

STUDY_YEARS = tuple(range(2018, 2026))
CHUNK_ROWS = 100_000

EXPECTED_COLUMNS = [
    "企业名称",
    "股票简称",
    "关联股票代码",
    "与上市公司关系",
    "上市公司行业",
    "招聘发布年份",
    "招聘结束年份",
    "招聘岗位",
    "工作城市",
    "工作区域",
    "最低月薪",
    "最高月薪",
    "职位描述",
    "学历要求",
    "要求经验",
    "招聘人数",
    "招聘类别",
    "初级分类",
    "公司地点",
    "工作地点",
    "招聘发布日期",
    "招聘结束日期",
    "来源",
]

CORE_COLUMNS = [
    "企业名称",
    "关联股票代码",
    "招聘岗位",
    "职位描述",
    "最低月薪",
    "最高月薪",
    "工作城市",
    "上市公司行业",
    "学历要求",
    "要求经验",
    "招聘发布日期",
    "招聘结束日期",
    "来源",
]

CATEGORY_COLUMNS = [
    "学历要求",
    "要求经验",
    "招聘类别",
    "初级分类",
    "工作城市",
    "来源",
]

DATE_COLUMNS = ["招聘发布日期", "招聘结束日期"]
SALARY_COLUMNS = ["最低月薪", "最高月薪"]

CONTENT_ID_COLUMNS = [
    "企业名称",
    "招聘岗位",
    "工作城市",
    "招聘发布日期",
    "职位描述",
]

BLANK_MARKERS = {"", "nan", "none", "null", "na", "n/a", ".", "-", "--", "—"}
YEAR_RE = re.compile(r"(19|20)\d{2}")


def now_text() -> str:
    return dt.datetime.now().isoformat(sep=" ", timespec="seconds")


def log(message: str) -> None:
    print(f"[{now_text()}] {message}", flush=True)


def ensure_read_only_inputs() -> dict[str, tuple[int, int]]:
    """记录原始文件的大小和修改时间，用于运行结束后的只读校验。"""
    snapshot: dict[str, tuple[int, int]] = {}
    for year in STUDY_YEARS:
        for suffix in ("csv", "dta"):
            path = RAW_ROOT / f"上市公司招聘数据{year}.{suffix}"
            if not path.is_file():
                raise FileNotFoundError(f"缺少原始文件：{path}")
            stat = path.stat()
            snapshot[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def verify_inputs_unchanged(before: dict[str, tuple[int, int]]) -> None:
    changed = []
    for raw_path, old_state in before.items():
        path = Path(raw_path)
        stat = path.stat()
        new_state = (stat.st_size, stat.st_mtime_ns)
        if new_state != old_state:
            changed.append(raw_path)
    if changed:
        raise RuntimeError("原始文件在审计期间发生变化：" + "；".join(changed))


def blank_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").fillna("").str.strip().str.lower()
    return text.isin(BLANK_MARKERS)


def normalize_text(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def numeric_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    text = normalize_text(series)
    blank = text.str.lower().isin(BLANK_MARKERS)
    cleaned = (
        text.str.replace(",", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.strip()
    )
    numeric = pd.to_numeric(cleaned.mask(blank), errors="coerce")
    parse_failed = (~blank) & numeric.isna()
    return numeric, parse_failed


def date_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    text = normalize_text(series)
    blank = text.str.lower().isin(BLANK_MARKERS)
    parsed = pd.to_datetime(text.mask(blank), errors="coerce", format="mixed")
    parse_failed = (~blank) & parsed.isna()
    return parsed, parse_failed


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def add_issue(
    rows: list[dict[str, Any]],
    *,
    year: int,
    issue_code: str,
    term: str,
    count: int,
    denominator: int,
    cleaning_impact: str,
    suggested_action: str,
    decision_owner: str,
) -> None:
    rows.append(
        {
            "year": year,
            "issue_code": issue_code,
            "term": term,
            "count": int(count),
            "denominator": int(denominator),
            "rate": safe_rate(int(count), int(denominator)),
            "cleaning_impact": cleaning_impact,
            "suggested_action": suggested_action,
            "decision_owner": decision_owner,
        }
    )


def update_top_values(counter: Counter[str], series: pd.Series, limit: int = 200) -> None:
    values = normalize_text(series)
    values = values[~values.str.lower().isin(BLANK_MARKERS)]
    counter.update(values.value_counts().head(limit).to_dict())
    if len(counter) > limit * 4:
        keep = counter.most_common(limit * 2)
        counter.clear()
        counter.update(dict(keep))


def decode_stata_text(value: Any) -> Any:
    """修复部分旧 DTA 把 GB18030 中文按 latin-1 暴露出来的问题。"""
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin-1").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    # 只有修复结果确实包含中文时才替换，避免破坏正常英文变量名。
    if any("\u4e00" <= char <= "\u9fff" for char in repaired):
        return repaired
    return value


def read_stata_utf8_varnames(path: Path, nvars: int) -> list[str] | None:
    """从 Stata 118/119 的 UTF-8 头部读取变量名。

    pandas 3.0 当前会把本项目 release 119 文件中的中文变量名显示为乱码，
    但文件头实际保存的是有效 UTF-8。直接读取 ``<varnames>`` 可保留中文。
    """
    with open(path, "rb") as handle:
        header = handle.read(2 * 1024 * 1024)
    release_match = re.search(rb"<release>(\d+)</release>", header)
    start_tag = b"<varnames>"
    end_tag = b"</varnames>"
    start = header.find(start_tag)
    end = header.find(end_tag)
    if release_match is None or start < 0 or end < 0:
        return None
    release = int(release_match.group(1))
    width = 129 if release >= 118 else 33
    block = header[start + len(start_tag) : end]
    if len(block) < nvars * width:
        return None
    names = []
    for index in range(nvars):
        raw = block[index * width : (index + 1) * width].split(b"\x00", 1)[0]
        names.append(raw.decode("utf-8", errors="replace"))
    return names


def read_dta_metadata(path: Path) -> dict[str, Any]:
    """只读取 Stata 文件头部元数据，不加载数 GB 的数据内容。"""
    reader = StataReader(path, convert_categoricals=False)
    try:
        # pandas 3.0 不再公开 nobs/varlist 属性，但头部解析结果仍由
        # StataReader 内部维护；这里只读取元数据，不读取数据区。
        reader._ensure_open()
        nvars = int(reader._nvar)
        varlist = read_stata_utf8_varnames(path, nvars)
        if varlist is None:
            varlist = [decode_stata_text(value) for value in reader._varlist]
        typlist = [f"str{value}" if isinstance(value, int) else str(value) for value in reader._typlist]
        nobs = int(reader._nobs)
        data_label = decode_stata_text(reader.data_label)
        time_stamp = reader.time_stamp
    finally:
        reader._close_file()
    return {
        "nobs": nobs,
        "nvars": nvars,
        "varlist": varlist,
        "typlist": typlist,
        "data_label": data_label,
        "time_stamp": str(time_stamp),
    }


def duplicate_hashes(frame: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    chosen = [c for c in columns if c in frame.columns]
    normalized = frame[chosen].astype("string").fillna("").apply(lambda s: s.str.strip())
    return pd.util.hash_pandas_object(normalized, index=False)


def capture_examples(
    target: list[dict[str, Any]],
    *,
    year: int,
    frame: pd.DataFrame,
    mask: pd.Series,
    issue_code: str,
    first_record_number: int,
    columns: Iterable[str],
    limit: int = 20,
) -> None:
    """每个年份、每类问题最多保留20个可追溯例子，避免泄露大段职位文本。"""
    existing = sum(1 for row in target if row["issue_code"] == issue_code)
    remaining = limit - existing
    if remaining <= 0:
        return
    positions = [index for index, flagged in enumerate(mask.fillna(False).tolist()) if flagged]
    for position in positions[:remaining]:
        raw_values = {}
        for name in columns:
            if name in frame.columns:
                value = str(frame.iloc[position][name])
                raw_values[name] = value[:200]
        target.append(
            {
                "year": year,
                "source_record_id": f"{year}-csv-{first_record_number + position:09d}",
                "issue_code": issue_code,
                "raw_values": json.dumps(raw_values, ensure_ascii=False),
            }
        )


def scan_csv(year: int, path: Path) -> dict[str, Any]:
    log(f"{year}：开始全量扫描 CSV（{path.stat().st_size / 1024**3:.2f} GiB）")
    started = time.perf_counter()
    total_rows = 0
    chunks = 0
    columns: list[str] | None = None
    missing = Counter()
    salary_counts = Counter()
    date_counts = Counter()
    year_counts = Counter()
    extra_column_nonblank = 0
    exact_duplicate_count = 0
    content_duplicate_count = 0
    seen_exact: set[int] = set()
    seen_content: set[int] = set()
    category_values: dict[str, Counter[str]] = {name: Counter() for name in CATEGORY_COLUMNS}
    company_code_pairs: set[tuple[str, str]] = set()
    salary_min: dict[str, float] = {name: math.inf for name in SALARY_COLUMNS}
    salary_max: dict[str, float] = {name: -math.inf for name in SALARY_COLUMNS}
    example_rows: list[dict[str, Any]] = []
    invalid_value_patterns: dict[str, Counter[str]] = {
        name: Counter() for name in SALARY_COLUMNS + DATE_COLUMNS
    }

    reader = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype="string",
        keep_default_na=False,
        chunksize=CHUNK_ROWS,
        engine="c",
        on_bad_lines="error",
        low_memory=False,
    )

    for chunks, frame in enumerate(reader, start=1):
        first_record_number = total_rows + 1
        if columns is None:
            columns = [str(c) for c in frame.columns]
        total_rows += len(frame)

        for name in CORE_COLUMNS:
            if name in frame.columns:
                missing[name] += int(blank_mask(frame[name]).sum())

        extra_columns = [c for c in frame.columns if str(c).startswith("Unnamed:") or str(c).strip() == ""]
        extra_mask = pd.Series(False, index=frame.index)
        for name in extra_columns:
            this_nonblank = ~blank_mask(frame[name])
            extra_column_nonblank += int(this_nonblank.sum())
            extra_mask |= this_nonblank
        if extra_columns:
            capture_examples(
                example_rows,
                year=year,
                frame=frame,
                mask=extra_mask,
                issue_code="EXTRA_COLUMN_NONBLANK",
                first_record_number=first_record_number,
                columns=extra_columns + ["来源"],
            )

        salary_numeric: dict[str, pd.Series] = {}
        for name in SALARY_COLUMNS:
            values, parse_failed = numeric_series(frame[name])
            salary_numeric[name] = values
            salary_counts[f"{name}_parse_failed"] += int(parse_failed.sum())
            invalid_value_patterns[name].update(
                normalize_text(frame.loc[parse_failed, name]).value_counts().head(200).to_dict()
            )
            salary_counts[f"{name}_zero"] += int((values == 0).sum())
            salary_counts[f"{name}_negative"] += int((values < 0).sum())
            salary_counts[f"{name}_over_100000"] += int((values > 100_000).sum())
            salary_counts[f"{name}_over_1000000"] += int((values > 1_000_000).sum())
            finite = values.dropna()
            if not finite.empty:
                salary_min[name] = min(salary_min[name], float(finite.min()))
                salary_max[name] = max(salary_max[name], float(finite.max()))

        both_salary = salary_numeric["最低月薪"].notna() & salary_numeric["最高月薪"].notna()
        salary_counts["salary_both_numeric"] += int(both_salary.sum())
        salary_counts["salary_inverted"] += int(
            (
                both_salary
                & (salary_numeric["最低月薪"] > salary_numeric["最高月薪"])
            ).sum()
        )
        salary_counts["salary_any_nonpositive"] += int(
            (
                (salary_numeric["最低月薪"].notna() & (salary_numeric["最低月薪"] <= 0))
                | (salary_numeric["最高月薪"].notna() & (salary_numeric["最高月薪"] <= 0))
            ).sum()
        )
        salary_parse_mask = pd.Series(False, index=frame.index)
        for name in SALARY_COLUMNS:
            _, parse_failed = numeric_series(frame[name])
            salary_parse_mask |= parse_failed
        capture_examples(
            example_rows,
            year=year,
            frame=frame,
            mask=salary_parse_mask,
            issue_code="SALARY_PARSE_FAILED",
            first_record_number=first_record_number,
            columns=SALARY_COLUMNS + ["来源"],
        )
        salary_inverted_mask = both_salary & (
            salary_numeric["最低月薪"] > salary_numeric["最高月薪"]
        )
        capture_examples(
            example_rows,
            year=year,
            frame=frame,
            mask=salary_inverted_mask,
            issue_code="SALARY_INVERTED",
            first_record_number=first_record_number,
            columns=SALARY_COLUMNS + ["来源"],
        )

        parsed_dates: dict[str, pd.Series] = {}
        for name in DATE_COLUMNS:
            values, parse_failed = date_series(frame[name])
            parsed_dates[name] = values
            date_counts[f"{name}_parse_failed"] += int(parse_failed.sum())
            invalid_value_patterns[name].update(
                normalize_text(frame.loc[parse_failed, name]).value_counts().head(200).to_dict()
            )

        both_dates = parsed_dates["招聘发布日期"].notna() & parsed_dates["招聘结束日期"].notna()
        date_counts["both_dates_parsed"] += int(both_dates.sum())
        date_counts["end_before_start"] += int(
            (
                both_dates
                & (parsed_dates["招聘结束日期"] < parsed_dates["招聘发布日期"])
            ).sum()
        )
        pub_date_year = parsed_dates["招聘发布日期"].dt.year
        end_date_year = parsed_dates["招聘结束日期"].dt.year
        date_counts["publish_date_year_not_file_year"] += int(
            (pub_date_year.notna() & (pub_date_year != year)).sum()
        )
        date_counts["end_date_outside_study_window"] += int(
            (end_date_year.notna() & ~end_date_year.between(2018, 2026)).sum()
        )
        date_parse_mask = pd.Series(False, index=frame.index)
        for name in DATE_COLUMNS:
            _, parse_failed = date_series(frame[name])
            date_parse_mask |= parse_failed
        capture_examples(
            example_rows,
            year=year,
            frame=frame,
            mask=date_parse_mask,
            issue_code="DATE_PARSE_FAILED",
            first_record_number=first_record_number,
            columns=DATE_COLUMNS + ["来源"],
        )
        end_before_mask = both_dates & (
            parsed_dates["招聘结束日期"] < parsed_dates["招聘发布日期"]
        )
        capture_examples(
            example_rows,
            year=year,
            frame=frame,
            mask=end_before_mask,
            issue_code="END_BEFORE_START",
            first_record_number=first_record_number,
            columns=DATE_COLUMNS + ["来源"],
        )
        publish_mismatch_mask = pub_date_year.notna() & (pub_date_year != year)
        capture_examples(
            example_rows,
            year=year,
            frame=frame,
            mask=publish_mismatch_mask,
            issue_code="PUBLISH_DATE_YEAR_MISMATCH",
            first_record_number=first_record_number,
            columns=["招聘发布年份", "招聘发布日期", "来源"],
        )

        for name, expected in (("招聘发布年份", year), ("招聘结束年份", None)):
            numeric, failed = numeric_series(frame[name])
            year_counts[f"{name}_parse_failed"] += int(failed.sum())
            if expected is not None:
                year_counts[f"{name}_not_file_year"] += int(
                    (numeric.notna() & (numeric != expected)).sum()
                )
            year_counts[f"{name}_outside_2018_2026"] += int(
                (numeric.notna() & ~numeric.between(2018, 2026)).sum()
            )

        exact_hash = duplicate_hashes(frame, EXPECTED_COLUMNS)
        for value in exact_hash.astype("uint64").tolist():
            if value in seen_exact:
                exact_duplicate_count += 1
            else:
                seen_exact.add(value)

        content_hash = duplicate_hashes(frame, CONTENT_ID_COLUMNS)
        for value in content_hash.astype("uint64").tolist():
            if value in seen_content:
                content_duplicate_count += 1
            else:
                seen_content.add(value)

        for name in CATEGORY_COLUMNS:
            if name in frame.columns:
                update_top_values(category_values[name], frame[name])

        if {"企业名称", "关联股票代码"}.issubset(frame.columns):
            pairs = frame[["关联股票代码", "企业名称"]].astype("string").fillna("")
            pairs["关联股票代码"] = pairs["关联股票代码"].str.strip()
            pairs["企业名称"] = pairs["企业名称"].str.strip()
            pairs = pairs[
                (~pairs["关联股票代码"].str.lower().isin(BLANK_MARKERS))
                & (~pairs["企业名称"].str.lower().isin(BLANK_MARKERS))
            ].drop_duplicates()
            company_code_pairs.update(map(tuple, pairs.itertuples(index=False, name=None)))

        if chunks % 5 == 0:
            log(f"{year}：已扫描 {total_rows:,} 条逻辑记录")

    elapsed = time.perf_counter() - started
    log(f"{year}：CSV 全量扫描完成，共 {total_rows:,} 条，耗时 {elapsed / 60:.1f} 分钟")

    return {
        "year": year,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "columns": columns or [],
        "nvars": len(columns or []),
        "rows": total_rows,
        "chunks": chunks,
        "elapsed_seconds": round(elapsed, 3),
        "missing": dict(missing),
        "salary_counts": dict(salary_counts),
        "salary_min": {k: (None if math.isinf(v) else v) for k, v in salary_min.items()},
        "salary_max": {k: (None if math.isinf(v) else v) for k, v in salary_max.items()},
        "date_counts": dict(date_counts),
        "year_counts": dict(year_counts),
        "extra_column_nonblank": extra_column_nonblank,
        "exact_duplicate_count": exact_duplicate_count,
        "content_duplicate_count": content_duplicate_count,
        "category_top_values": {
            name: counter.most_common(30) for name, counter in category_values.items()
        },
        "company_code_pairs": sorted(company_code_pairs),
        "example_rows": example_rows,
        "invalid_value_patterns": {
            name: counter.most_common(100) for name, counter in invalid_value_patterns.items()
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fmt_int(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}"


def fmt_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2%}"


def build_outputs(csv_results: list[dict[str, Any]], dta_results: dict[int, dict[str, Any]]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    year_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    category_rows: list[dict[str, Any]] = []
    example_rows: list[dict[str, Any]] = []
    invalid_pattern_rows: list[dict[str, Any]] = []
    all_pairs: set[tuple[int, str, str]] = set()

    for result in csv_results:
        year = result["year"]
        dta = dta_results[year]
        row_difference = result["rows"] - dta["nobs"]
        unnamed_columns = [
            c for c in result["columns"] if c.startswith("Unnamed:") or not c.strip()
        ]
        year_rows.append(
            {
                "year": year,
                "csv_rows": result["rows"],
                "dta_rows": dta["nobs"],
                "csv_minus_dta_rows": row_difference,
                "csv_variables": result["nvars"],
                "dta_variables": dta["nvars"],
                "unnamed_csv_columns": "; ".join(unnamed_columns),
                "unnamed_column_nonblank": result["extra_column_nonblank"],
                "exact_duplicate_rows_after_first": result["exact_duplicate_count"],
                "content_duplicate_rows_after_first": result["content_duplicate_count"],
                "scan_seconds": result["elapsed_seconds"],
            }
        )

        max_vars = max(result["nvars"], dta["nvars"])
        for position in range(max_vars):
            csv_name = result["columns"][position] if position < result["nvars"] else ""
            dta_name = dta["varlist"][position] if position < dta["nvars"] else ""
            dta_type = dta["typlist"][position] if position < dta["nvars"] else ""
            schema_rows.append(
                {
                    "year": year,
                    "position": position + 1,
                    "csv_column": csv_name,
                    "dta_variable": dta_name,
                    "dta_storage_type": dta_type,
                    "same_name": csv_name == dta_name,
                }
            )

        for name in CORE_COLUMNS:
            count = int(result["missing"].get(name, 0))
            missing_rows.append(
                {
                    "year": year,
                    "variable": name,
                    "missing_count": count,
                    "total_rows": result["rows"],
                    "missing_rate": safe_rate(count, result["rows"]),
                }
            )

        if row_difference:
            add_issue(
                issue_rows,
                year=year,
                issue_code="CSV_DTA_ROW_COUNT_DIFF",
                term="CSV 与 DTA 记录数不一致",
                count=abs(row_difference),
                denominator=max(result["rows"], dta["nobs"]),
                cleaning_impact="必须先明确后续清洗以哪个文件为准，否则样本量无法复现。",
                suggested_action="CSV 作为主输入；对差异年份单独定位缺失或新增记录，并保留核对说明。",
                decision_owner="数据负责人确认",
            )

        issue_specs = [
            (
                "EXTRA_COLUMN_NONBLANK",
                "空白列出现非空值",
                result["extra_column_nonblank"],
                "直接丢弃空白列可能损失信息或掩盖错位记录。",
                "先导出异常记录的来源行号和相邻字段，再判断是误写、错位还是可安全删除。",
                "数据负责人确认",
            ),
            (
                "SALARY_ANY_NONPOSITIVE",
                "至少一个工资端点小于或等于零",
                result["salary_counts"].get("salary_any_nonpositive", 0),
                "无法直接计算合理的工资中点或对数工资。",
                "保留原值并加异常标记；是否删除、设为缺失或采用另一端点须在清洗规则中明确。",
                "项目组与导师决定",
            ),
            (
                "SALARY_INVERTED",
                "最低月薪高于最高月薪",
                result["salary_counts"].get("salary_inverted", 0),
                "工资区间方向错误，可能来自录入或字段错位。",
                "抽样查看原始记录；只有证据充分时才交换上下限，否则标记为异常。",
                "项目组决定",
            ),
            (
                "SALARY_PARSE_FAILED",
                "工资字段非空但无法转成数值",
                result["salary_counts"].get("最低月薪_parse_failed", 0)
                + result["salary_counts"].get("最高月薪_parse_failed", 0),
                "工资变量无法直接用于计算和回归。",
                "整理原始写法及频数，制定统一解析规则；无法可靠解释的值保留原值并设为缺失。",
                "数据负责人提出规则，项目组复核",
            ),
            (
                "DATE_PARSE_FAILED",
                "日期字段非空但无法解析",
                result["date_counts"].get("招聘发布日期_parse_failed", 0)
                + result["date_counts"].get("招聘结束日期_parse_failed", 0),
                "无法可靠构造年份、月份和广告持续时间。",
                "按原始格式分组制定解析规则，保留原始日期和解析失败标记。",
                "数据负责人提出规则",
            ),
            (
                "END_BEFORE_START",
                "招聘结束日期早于发布日期",
                result["date_counts"].get("end_before_start", 0),
                "广告持续时间为负，可能影响时间变量。",
                "抽样核对；不要自动交换日期，除非确认是固定的字段颠倒。",
                "项目组决定",
            ),
            (
                "PUBLISH_DATE_YEAR_MISMATCH",
                "发布日期年份与文件年份不一致",
                result["date_counts"].get("publish_date_year_not_file_year", 0),
                "按文件名赋年份可能产生错误的年度分类。",
                "比较发布日期、招聘发布年份和文件年份，确定年度变量的优先顺序。",
                "项目组与导师决定",
            ),
            (
                "EXACT_DUPLICATE",
                "完全重复记录",
                result["exact_duplicate_count"],
                "重复广告会重复计权并影响样本量。",
                "清洗时生成来源记录 ID；完全重复记录是否去重需保留去重前后数量。",
                "项目组决定",
            ),
            (
                "CONTENT_DUPLICATE",
                "核心内容相同的疑似重复广告",
                result["content_duplicate_count"],
                "同一广告重复发布与真实多次招聘可能混在一起。",
                "先作为疑似重复标记，不直接删除；比较来源、结束日期和其他字段后制定规则。",
                "项目组与导师决定",
            ),
        ]
        for code, term, count, impact, action, owner in issue_specs:
            add_issue(
                issue_rows,
                year=year,
                issue_code=code,
                term=term,
                count=int(count),
                denominator=result["rows"],
                cleaning_impact=impact,
                suggested_action=action,
                decision_owner=owner,
            )

        for variable, values in result["category_top_values"].items():
            for rank, (value, count) in enumerate(values, start=1):
                category_rows.append(
                    {
                        "year": year,
                        "variable": variable,
                        "rank": rank,
                        "raw_value": value,
                        "count": count,
                    }
                )

        for code, company in result["company_code_pairs"]:
            all_pairs.add((year, code, company))
        example_rows.extend(result["example_rows"])
        for variable, values in result["invalid_value_patterns"].items():
            for rank, (raw_value, count) in enumerate(values, start=1):
                invalid_pattern_rows.append(
                    {
                        "year": year,
                        "variable": variable,
                        "rank": rank,
                        "raw_value": raw_value,
                        "count": count,
                    }
                )

    code_names: dict[str, set[str]] = defaultdict(set)
    code_years: dict[str, set[int]] = defaultdict(set)
    for year, code, company in all_pairs:
        code_names[code].add(company)
        code_years[code].add(year)
    conflict_rows = [
        {
            "stock_code": code,
            "distinct_company_names": len(names),
            "years_present": ";".join(map(str, sorted(code_years[code]))),
            "company_names": " | ".join(sorted(names)),
        }
        for code, names in sorted(code_names.items())
        if len(names) > 1
    ]

    write_csv(
        OUT_ROOT / "year_summary.csv",
        year_rows,
        [
            "year",
            "csv_rows",
            "dta_rows",
            "csv_minus_dta_rows",
            "csv_variables",
            "dta_variables",
            "unnamed_csv_columns",
            "unnamed_column_nonblank",
            "exact_duplicate_rows_after_first",
            "content_duplicate_rows_after_first",
            "scan_seconds",
        ],
    )
    write_csv(
        OUT_ROOT / "schema_comparison.csv",
        schema_rows,
        ["year", "position", "csv_column", "dta_variable", "dta_storage_type", "same_name"],
    )
    write_csv(
        OUT_ROOT / "missing_summary.csv",
        missing_rows,
        ["year", "variable", "missing_count", "total_rows", "missing_rate"],
    )
    write_csv(
        OUT_ROOT / "issue_register.csv",
        issue_rows,
        [
            "year",
            "issue_code",
            "term",
            "count",
            "denominator",
            "rate",
            "cleaning_impact",
            "suggested_action",
            "decision_owner",
        ],
    )
    write_csv(
        OUT_ROOT / "category_top_values.csv",
        category_rows,
        ["year", "variable", "rank", "raw_value", "count"],
    )
    write_csv(
        OUT_ROOT / "company_code_conflicts.csv",
        conflict_rows,
        ["stock_code", "distinct_company_names", "years_present", "company_names"],
    )
    write_csv(
        OUT_ROOT / "special_record_examples.csv",
        example_rows,
        ["year", "source_record_id", "issue_code", "raw_values"],
    )
    write_csv(
        OUT_ROOT / "invalid_value_patterns.csv",
        invalid_pattern_rows,
        ["year", "variable", "rank", "raw_value", "count"],
    )

    raw_json = []
    for result in csv_results:
        compact = dict(result)
        compact.pop("company_code_pairs", None)
        compact.pop("example_rows", None)
        raw_json.append(compact)
    with open(OUT_ROOT / "audit_details.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"generated_at": now_text(), "csv": raw_json, "dta": dta_results},
            handle,
            ensure_ascii=False,
            indent=2,
        )

    total_csv = sum(row["csv_rows"] for row in year_rows)
    total_dta = sum(row["dta_rows"] for row in year_rows)
    total_exact_dup = sum(row["exact_duplicate_rows_after_first"] for row in year_rows)
    total_content_dup = sum(row["content_duplicate_rows_after_first"] for row in year_rows)
    nonzero_issues = [row for row in issue_rows if row["count"] > 0]

    report_lines = [
        "# 2018—2025年招聘原始数据审计报告",
        "",
        f"> 生成时间：{now_text()}",
        "> 审计方式：CSV 全量逐块扫描；DTA 读取元数据进行交叉核验；原始文件严格只读。",
        "",
        "## 一句话结论",
        "",
        "本次审计已经把后续清洗最需要先处理的问题按年份、数量和影响列出。清洗程序可以据此逐项增加规则和异常标记，但工资异常、重复广告和企业名称合并等会影响研究结论的事项，仍需项目组确认后才能定稿。",
        "",
        "## 1 审计范围和读法",
        "",
        f"- 研究年份：2018—2025年。",
        f"- CSV 全量记录：{total_csv:,} 条；DTA 元数据记录：{total_dta:,} 条。",
        "- 逻辑记录：CSV 解析器识别的一条完整招聘广告。职位描述即使包含换行，也仍算一条记录。",
        "- 异常标记：指出记录可能需要处理，但不等于该记录一定要删除。",
        "- 本报告先说明问题对清洗的影响；完整数字同时保存在同目录 CSV 文件中。",
        "",
        "## 2 各年度文件和记录数",
        "",
        "| 年份 | CSV记录数 | DTA记录数 | CSV-DTA差 | CSV字段数 | 空白列非空记录 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in year_rows:
        report_lines.append(
            f"| {row['year']} | {fmt_int(row['csv_rows'])} | {fmt_int(row['dta_rows'])} | "
            f"{fmt_int(row['csv_minus_dta_rows'])} | {row['csv_variables']} | "
            f"{fmt_int(row['unnamed_column_nonblank'])} |"
        )

    report_lines.extend(
        [
            "",
            "**怎样理解：**CSV 将作为清洗主输入；DTA 用来核对记录数和结构。若同一年两者记录数不同，后续必须保留差异说明，不能在两个文件之间随意切换。",
            "",
            "## 3 直接影响清洗的问题",
            "",
            "下表只显示数量大于零的问题。‘建议动作’是下一步做法，不代表已经决定删除或修改记录。",
            "",
            "| 年份 | 问题 | 数量 | 占当年比例 | 为什么影响清洗 |",
            "|---:|---|---:|---:|---|",
        ]
    )
    for row in nonzero_issues:
        report_lines.append(
            f"| {row['year']} | {row['term']} | {fmt_int(row['count'])} | "
            f"{fmt_rate(row['rate'])} | {row['cleaning_impact']} |"
        )

    high_missing = sorted(
        (row for row in missing_rows if (row["missing_rate"] or 0) >= 0.01),
        key=lambda row: (row["year"], -(row["missing_rate"] or 0), row["variable"]),
    )
    report_lines.extend(
        [
            "",
            "## 4 核心字段缺失情况",
            "",
            "下表列出缺失率达到1%的字段。这里的缺失包括空白，以及 `-`、`--` 等表示未填写的占位符。缺失率高不一定说明文件损坏，但会减少可用于特定分析的样本。",
            "",
            "| 年份 | 字段 | 缺失数量 | 缺失率 |",
            "|---:|---|---:|---:|",
        ]
    )
    for row in high_missing:
        report_lines.append(
            f"| {row['year']} | {row['variable']} | {fmt_int(row['missing_count'])} | "
            f"{fmt_rate(row['missing_rate'])} |"
        )

    report_lines.extend(
        [
            "",
            "## 5 重复记录与企业标识",
            "",
            f"- 完全重复记录中，除第一次出现外共有 {total_exact_dup:,} 条。",
            f"- 核心内容相同的疑似重复广告中，除第一次出现外共有 {total_content_dup:,} 条。",
            f"- 有 {len(conflict_rows):,} 个股票代码对应多个企业名称。",
            "",
            "‘疑似重复’不等于可以直接删除。同一企业可能重复发布真实岗位，也可能是同一广告被多个来源收录。清洗时应先生成来源记录 ID 和内容 ID，再保留去重前后样本量。企业名称也不能仅因股票代码相同就自动合并，需区分简称、子公司和名称变更。",
            "",
            "## 6 建议的数据清洗顺序",
            "",
            "1. 统一23个正式字段，保留空白第24列及其异常标记，确认后再决定是否移除。",
            "2. 为每条原始记录生成来源记录 ID，格式建议为“年份-来源文件-逻辑行号”。",
            "3. 保留工资和日期原值，另外生成数值化字段、解析失败标记和异常标记。",
            "4. 统一缺失值表示，但不要把0工资直接当作普通缺失值而不留标记。",
            "5. 生成内容 ID 和疑似重复标记；由项目组确定正式去重规则。",
            "6. 建立股票代码与企业名称映射表，对一对多关系单独复核。",
            "7. 每一步输出处理前后记录数，形成样本筛选流程表。",
            "",
            "## 7 需要项目组或导师决定的问题",
            "",
            "- 工资端点为0、负数、上下限倒置或极端高值时，分别如何处理？",
            "- 年度变量优先采用文件年份、招聘发布年份，还是由发布日期推导？",
            "- 完全重复和疑似重复广告分别采用什么去重范围和保留顺序？",
            "- 股票代码对应多个企业名称时，分析单位是招聘企业、上市公司还是两者并存？",
            "- CSV 与 DTA 记录数不一致的年份，是否统一以 CSV 为正式来源？",
            "",
            "## 8 术语说明",
            "",
            "- **字段**：数据表中的一列，例如最低月薪或招聘发布日期。",
            "- **逻辑记录**：解析后的一条完整招聘广告，不等同于文本文件中的一行。",
            "- **缺失率**：某字段没有有效内容的记录数，占当年全部记录的比例。",
            "- **解析失败**：原始内容非空，但程序无法把它可靠转换成数值或日期。",
            "- **异常值**：明显不符合通常范围或字段关系的值；它需要检查，但不一定错误。",
            "- **来源记录 ID**：用于追溯原始文件和原始位置的编号。",
            "- **内容 ID**：根据多项内容生成的编号，用于寻找可能重复的广告。",
            "- **元数据**：描述文件结构的信息，例如变量名、变量类型和观测数，不是具体招聘内容。",
            "",
            "## 9 配套文件",
            "",
            "- `year_summary.csv`：年度记录数、字段数和重复情况总表。",
            "- `schema_comparison.csv`：CSV 与 DTA 的字段结构对照。",
            "- `missing_summary.csv`：核心字段缺失数量和缺失率。",
            "- `issue_register.csv`：问题、影响、建议动作和决策责任人。",
            "- `category_top_values.csv`：主要分类字段的高频原始取值，供制定统一编码规则。",
            "- `company_code_conflicts.csv`：一个股票代码对应多个企业名称的清单。",
            "- `special_record_examples.csv`：部分异常记录的可追溯例子，不含完整职位描述。",
            "- `invalid_value_patterns.csv`：工资和日期无法转换时的原始写法及频数。",
            "- `audit_details.json`：程序可直接读取的完整审计结果。",
        ]
    )
    (OUT_ROOT / "data_audit_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    handoff_lines = [
        "# 数据清洗交接说明",
        "",
        f"> 交接版本生成于 {now_text()}。本说明面向项目组成员和后续接手的 Codex。",
        "",
        "## 1 从哪里开始",
        "",
        "1. 先读 `data_audit_report.md`，理解问题及其对清洗的影响。",
        "2. 再看 `issue_register.csv`，逐项确定清洗规则和决策责任人。",
        "3. 编写清洗程序时读取 `audit_details.json` 与各 CSV 汇总表，不要从报告文字中手工抄数字。",
        "4. 原始目录严格只读；清洗结果写入 `D:/SRTP/工作数据/curated`。",
        "",
        "## 2 重新运行审计",
        "",
        "在仓库根目录执行：",
        "",
        "```powershell",
        "powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `",
        "  -ScriptPath code/python/01_audit_raw_data.py",
        "```",
        "",
        "运行成功时，终端最后应出现 `AUDIT_GATE=PASS` 和 `PYTHON_TASK=PASS`。",
        "",
        "## 3 清洗程序必须继承的约束",
        "",
        "- 不覆盖、移动或重命名原始 CSV/DTA。",
        "- 保留全部23个正式字段的原始值。",
        "- 新生成清洗值时，同时保留解析失败和异常标记。",
        "- 每一步记录输入数、输出数、删除数和删除原因。",
        "- 工资、日期、重复广告和企业识别规则必须可配置，不写成无法追溯的隐含操作。",
        "- 大型数据不提交 Git；Git 只保存程序、规则、日志摘要和小型质量检查结果。",
        "",
        "## 4 建议的清洗程序接口",
        "",
        "输入：年份和对应 CSV 路径。",
        "",
        "输出至少包括：",
        "",
        "- 当年标准化 Parquet；",
        "- 当年质量检查表；",
        "- 字段转换与异常数量表；",
        "- 样本筛选流程表；",
        "- 运行日志；",
        "- 规则版本号。",
        "",
        "## 5 尚未授权自动执行的研究决策",
        "",
        "以下事项在项目组确认前只能生成标记，不能自动删除或改写：",
        "",
        "- 0工资、负工资、倒置工资区间和极端工资；",
        "- 日期与文件年份不一致；",
        "- 完全重复或疑似重复广告；",
        "- 一个股票代码对应多个企业名称；",
        "- CSV 与 DTA 不一致记录的取舍。",
    ]
    (OUT_ROOT / "cleaning_handoff.md").write_text("\n".join(handoff_lines) + "\n", encoding="utf-8")


def main() -> int:
    started = time.perf_counter()
    log("=== 2018—2025 年原始数据全量审计开始 ===")
    if not RAW_ROOT.is_dir():
        raise FileNotFoundError(f"原始数据目录不存在：{RAW_ROOT}")
    before = ensure_read_only_inputs()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    dta_results: dict[int, dict[str, Any]] = {}
    for year in STUDY_YEARS:
        path = RAW_ROOT / f"上市公司招聘数据{year}.dta"
        log(f"{year}：读取 DTA 元数据")
        dta_results[year] = read_dta_metadata(path)

    csv_results = []
    for year in STUDY_YEARS:
        path = RAW_ROOT / f"上市公司招聘数据{year}.csv"
        csv_results.append(scan_csv(year, path))

    build_outputs(csv_results, dta_results)
    verify_inputs_unchanged(before)
    elapsed = time.perf_counter() - started
    log(f"审计结果目录：{OUT_ROOT}")
    log(f"总耗时：{elapsed / 60:.1f} 分钟")
    log("AUDIT_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
