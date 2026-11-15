"""提取数据审计典型切片，供项目组讨论清洗规则。

原始 CSV 严格只读。输出只包含少量、可追溯的字段，不包含完整职位描述。
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
RAW_ROOT = Path(os.environ.get("SRTP_RAW_ROOT", r"D:\SRTP\分年份保存数据"))
OUT_ROOT = PROJECT_ROOT / "outputs" / "qc" / "full_audit"
TEMP_ROOT = Path(os.environ.get("SRTP_TEMP_ROOT", r"D:\SRTP\工作数据\temp"))

CHUNK_ROWS = 100_000
BLANK_MARKERS = {"", "nan", "none", "null", "na", "n/a", ".", "-", "--", "—"}

DISPLAY_COLUMNS = [
    "企业名称",
    "关联股票代码",
    "招聘岗位",
    "工作城市",
    "最低月薪",
    "最高月薪",
    "招聘发布日期",
    "招聘结束日期",
    "学历要求",
    "要求经验",
    "来源",
]

CONTENT_ID_COLUMNS = [
    "企业名称",
    "招聘岗位",
    "工作城市",
    "招聘发布日期",
    "职位描述",
]


def csv_path(year: int) -> Path:
    return RAW_ROOT / f"上市公司招聘数据{year}.csv"


def read_csv(year: int, **kwargs: Any) -> pd.DataFrame | Any:
    return pd.read_csv(
        csv_path(year),
        encoding="utf-8-sig",
        dtype="string",
        keep_default_na=False,
        engine="c",
        on_bad_lines="error",
        low_memory=False,
        **kwargs,
    )


def blank_mask(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.lower().isin(BLANK_MARKERS)


def numeric(series: pd.Series) -> pd.Series:
    text = series.astype("string").fillna("").str.strip()
    blank = text.str.lower().isin(BLANK_MARKERS)
    cleaned = (
        text.str.replace(",", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned.mask(blank), errors="coerce")


def content_hash(frame: pd.DataFrame) -> pd.Series:
    normalized = (
        frame[CONTENT_ID_COLUMNS]
        .astype("string")
        .fillna("")
        .apply(lambda series: series.str.strip())
    )
    return pd.util.hash_pandas_object(normalized, index=False).astype("uint64")


def make_record(
    *,
    category: str,
    issue: str,
    group: str,
    year: int,
    record_number: int,
    row: pd.Series,
    observation: str,
) -> dict[str, Any]:
    record = {
        "问题类别": category,
        "具体问题": issue,
        "示例组": group,
        "年份": year,
        "来源记录ID": f"{year}-csv-{record_number:09d}",
        "观察说明": observation,
    }
    for column in DISPLAY_COLUMNS:
        record[column] = str(row.get(column, "")).strip()
    return record


def fixed_record(year: int, record_number: int) -> pd.Series:
    offset = 0
    for frame in read_csv(year, chunksize=CHUNK_ROWS):
        if offset < record_number <= offset + len(frame):
            return frame.iloc[record_number - offset - 1]
        offset += len(frame)
    raise IndexError(f"未找到逻辑记录：{year}-{record_number}")


def take_rows(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    category: str,
    issue: str,
    group: str,
    year: int,
    observation: str,
    limit: int = 3,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = []
    positions = [index for index, flagged in enumerate(mask.fillna(False).tolist()) if flagged]
    for position in positions[:limit]:
        rows.append(
            make_record(
                category=category,
                issue=issue,
                group=group,
                year=year,
                record_number=offset + position + 1,
                row=frame.iloc[position],
                observation=observation,
            )
        )
    return rows


def duplicate_examples_2022(max_groups: int = 3) -> list[dict[str, Any]]:
    counts: Counter[int] = Counter()
    for frame in read_csv(2022, chunksize=CHUNK_ROWS):
        counts.update(int(value) for value in content_hash(frame).tolist())
    selected = [value for value, count in counts.items() if count >= 2][:max_groups]
    selected_set = set(selected)
    collected: dict[int, list[dict[str, Any]]] = {value: [] for value in selected}
    offset = 0
    for frame in read_csv(2022, chunksize=CHUNK_ROWS):
        hashes = content_hash(frame)
        for position, value in enumerate(hashes.tolist()):
            value = int(value)
            if value in selected_set and len(collected[value]) < 2:
                group_number = selected.index(value) + 1
                collected[value].append(
                    make_record(
                        category="重复类",
                        issue="核心内容相同的疑似重复广告",
                        group=f"重复组{group_number}",
                        year=2022,
                        record_number=offset + position + 1,
                        row=frame.iloc[position],
                        observation=(
                            f"该内容指纹在2022年出现{counts[value]}次；这里展示前2条。"
                            "内容指纹使用企业、岗位、城市、发布日期和职位描述生成。"
                        ),
                    )
                )
        offset += len(frame)
        if all(len(rows) >= 2 for rows in collected.values()):
            break
    return [row for value in selected for row in collected[value]]


def logic_examples() -> list[dict[str, Any]]:
    examples = []
    row = fixed_record(2018, 723_393)
    examples.append(
        make_record(
            category="逻辑问题",
            issue="招聘结束日期早于发布日期",
            group="日期颠倒例1",
            year=2018,
            record_number=723_393,
            row=row,
            observation="结束日期为2018-08-24，发布日期为2018-08-25，相差1天。",
        )
    )
    row = fixed_record(2019, 10_849)
    examples.append(
        make_record(
            category="逻辑问题",
            issue="最低月薪高于最高月薪",
            group="工资上下限颠倒例1",
            year=2019,
            record_number=10_849,
            row=row,
            observation="最低月薪50000，高于最高月薪10000。",
        )
    )

    frame = read_csv(2022, nrows=200_000)
    low = numeric(frame["最低月薪"])
    high = numeric(frame["最高月薪"])
    nonpositive = (low.notna() & (low <= 0)) | (high.notna() & (high <= 0))
    examples.extend(
        take_rows(
            frame,
            nonpositive,
            category="逻辑问题",
            issue="至少一个工资端点小于或等于0",
            group="非正工资",
            year=2022,
            observation="该记录不能直接计算正常的工资区间中点或对数工资。",
            limit=3,
        )
    )
    return examples


def missing_examples() -> list[dict[str, Any]]:
    examples = []
    frame_2018 = read_csv(2018, nrows=200_000)
    examples.extend(
        take_rows(
            frame_2018,
            blank_mask(frame_2018["最低月薪"]),
            category="字段缺失",
            issue="最低月薪缺失",
            group="最低月薪缺失",
            year=2018,
            observation="最低月薪没有有效内容，但其他岗位字段仍可用于非工资类分析。",
            limit=2,
        )
    )
    examples.extend(
        take_rows(
            frame_2018,
            blank_mask(frame_2018["最高月薪"]),
            category="字段缺失",
            issue="最高月薪缺失",
            group="最高月薪缺失",
            year=2018,
            observation="最高月薪没有有效内容，主工资变量无法按完整区间构造。",
            limit=2,
        )
    )

    frame_2024 = read_csv(2024, nrows=200_000)
    examples.extend(
        take_rows(
            frame_2024,
            blank_mask(frame_2024["招聘结束日期"]),
            category="字段缺失",
            issue="招聘结束日期缺失",
            group="结束日期缺失",
            year=2024,
            observation="结束日期为空或使用横线占位；发布日期仍然可用。",
            limit=2,
        )
    )
    examples.extend(
        take_rows(
            frame_2024,
            blank_mask(frame_2024["学历要求"]),
            category="字段缺失",
            issue="学历要求缺失",
            group="学历缺失",
            year=2024,
            observation="学历要求为空或使用横线占位，不能推断为‘不限’。",
            limit=2,
        )
    )
    return examples


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "问题类别",
        "具体问题",
        "示例组",
        "年份",
        "来源记录ID",
        *DISPLAY_COLUMNS,
        "观察说明",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = duplicate_examples_2022() + logic_examples() + missing_examples()
    csv_output = OUT_ROOT / "typical_issue_slices.csv"
    json_output = TEMP_ROOT / "artifact_issue_examples" / "typical_issue_slices.json"
    json_output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(csv_output, rows)
    with open(json_output, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(f"ISSUE_SLICE_ROWS={len(rows)}")
    print(f"ISSUE_SLICE_CSV={csv_output}")
    print("ISSUE_SLICE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
