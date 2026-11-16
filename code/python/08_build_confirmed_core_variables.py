"""构造当前已确认的基准核心变量。

本步骤只生成规则已经明确的变量：wage_mid、ln_wage、education、
experience和year_month。firm_id、occupation_id、city_id及非AI技能变量
在口径讨论完成前不生成。
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "confirmed_core_v1_summary.csv"
UNMAPPED_PATH = PROJECT_ROOT / "outputs" / "qc" / "confirmed_core_v1_unmapped_values.csv"
YEARS = tuple(range(2018, 2026))
BATCH_ROWS = 200_000

EDUCATION_CATEGORIES = ("不限", "高中及以下", "大专", "本科", "硕士", "博士")
EXPERIENCE_CATEGORIES = ("不限/应届", "1年以内", "1—3年", "3—5年", "5年以上")

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("wage_mid", pa.float64(), nullable=False),
        pa.field("ln_wage", pa.float64(), nullable=False),
        pa.field("education", pa.string()),
        pa.field("experience", pa.string()),
        pa.field("year_month", pa.date32()),
    ]
)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    text = re.sub(r"\s+", "", text)
    if not text or text.lower() in {"nan", "none", "null", "-", "--", "—"}:
        return None
    return text


@lru_cache(maxsize=None)
def map_education_text(text: str) -> str | None:
    """把学历要求映射为最低学历要求的大类。"""
    if re.search(r"不限|无学历要求|无要求", text):
        return "不限"
    if text in {"其他", "其它", "以上"}:
        return None
    if re.search(r"本科以下|硕士以下|博士以下", text):
        return None
    if "大专以下" in text:
        return "高中及以下"
    if re.search(r"小学|初中|高中|中专|中技|技校|职高|中职", text):
        return "高中及以下"
    if re.search(r"大专|专科|高职", text):
        return "大专"
    if re.search(r"本科|学士", text):
        return "本科"
    if re.search(r"硕士|MBA|EMBA", text, flags=re.IGNORECASE):
        return "硕士"
    if "博士" in text:
        return "博士"
    if "研究生" in text:
        return "硕士"
    return None


def map_education(value: object) -> tuple[str | None, str]:
    text = normalize_text(value)
    if text is None:
        return None, "missing"
    mapped = map_education_text(text)
    return (mapped, "mapped") if mapped is not None else (None, "unmapped")


CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def chinese_number_to_int(token: str) -> int:
    if token == "十":
        return 10
    if "十" in token:
        left, right = token.split("十", 1)
        tens = CHINESE_DIGITS.get(left, 1) if left else 1
        units = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + units
    digits = [CHINESE_DIGITS[char] for char in token if char in CHINESE_DIGITS]
    if not digits:
        raise ValueError(token)
    value = 0
    for digit in digits:
        value = value * 10 + digit
    return value


def replace_chinese_numbers(text: str) -> str:
    pattern = re.compile(r"[零一二两三四五六七八九十]+")
    return pattern.sub(lambda match: str(chinese_number_to_int(match.group(0))), text)


@lru_cache(maxsize=None)
def map_experience_text(text: str) -> str | None:
    """按最低工作年限把经验要求映射为五类。"""
    if re.search(r"不限|应届|在校|在读|无需经验|无需工作经验|无工作经验|无经验|无要求|不要求经验|经验无要求|零经验", text):
        return "不限/应届"
    if text == "无" or re.search(r"^0年(以上|及以上)?$", text):
        return "不限/应届"

    normalized = replace_chinese_numbers(text)
    normalized = normalized.replace("个月", "月")
    if re.search(r"半年|6月|六个月|不满1年|不到1年", text):
        return "1年以内"
    if re.search(r"1年(以内|以下)", normalized):
        return "1年以内"

    number_match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if number_match is None:
        return None
    minimum_years = float(number_match.group(1))
    if not math.isfinite(minimum_years) or minimum_years < 0:
        return None
    if minimum_years < 1:
        return "1年以内"
    if minimum_years < 3:
        return "1—3年"
    if minimum_years < 5:
        return "3—5年"
    return "5年以上"


def map_experience(value: object) -> tuple[str | None, str]:
    text = normalize_text(value)
    if text is None:
        return None, "missing"
    mapped = map_experience_text(text)
    return (mapped, "mapped") if mapped is not None else (None, "unmapped")


def snapshot(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    input_root = Path(storage["curated_root"]) / "cleaned_v1"
    output_root = Path(storage["features_root"]) / "confirmed_core_v1"
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    unmapped_education: Counter[str] = Counter()
    unmapped_experience: Counter[str] = Counter()
    input_snapshots: dict[str, tuple[int, int]] = {}

    for year in YEARS:
        input_path = input_root / f"jobs_{year}_cleaned.parquet"
        output_path = output_root / f"jobs_{year}_confirmed_core.parquet"
        temp_path = output_root / f"jobs_{year}_confirmed_core.parquet.tmp"
        if not input_path.is_file():
            raise FileNotFoundError(input_path)
        input_snapshots[str(input_path)] = snapshot(input_path)
        if temp_path.exists():
            temp_path.unlink()

        parquet = pq.ParquetFile(input_path)
        writer: pq.ParquetWriter | None = None
        input_rows = 0
        education_missing = 0
        education_unmapped = 0
        experience_missing = 0
        experience_unmapped = 0
        year_month_missing = 0

        try:
            for batch in parquet.iter_batches(
                batch_size=BATCH_ROWS,
                columns=["来源记录ID", "月薪代表值", "学历要求", "要求经验", "招聘发布日期"],
            ):
                frame = batch.to_pandas()
                wage_mid = pd.to_numeric(frame["月薪代表值"], errors="coerce").astype("float64")
                if wage_mid.isna().any() or (wage_mid <= 0).any():
                    raise RuntimeError(f"{year}年存在无效月薪代表值")

                education_results = frame["学历要求"].map(map_education)
                education = education_results.map(lambda item: item[0])
                education_status = education_results.map(lambda item: item[1])
                experience_results = frame["要求经验"].map(map_experience)
                experience = experience_results.map(lambda item: item[0])
                experience_status = experience_results.map(lambda item: item[1])

                education_missing += int((education_status == "missing").sum())
                education_unmapped += int((education_status == "unmapped").sum())
                experience_missing += int((experience_status == "missing").sum())
                experience_unmapped += int((experience_status == "unmapped").sum())

                for raw_value in frame.loc[education_status == "unmapped", "学历要求"]:
                    unmapped_education[str(raw_value).strip()] += 1
                for raw_value in frame.loc[experience_status == "unmapped", "要求经验"]:
                    unmapped_experience[str(raw_value).strip()] += 1

                publish_date = pd.to_datetime(frame["招聘发布日期"], errors="coerce")
                year_month = publish_date.dt.to_period("M").dt.to_timestamp()
                year_month_missing += int(year_month.isna().sum())

                output = pd.DataFrame(
                    {
                        "source_record_id": frame["来源记录ID"].astype("string"),
                        "wage_mid": wage_mid,
                        "ln_wage": np.log(wage_mid),
                        "education": education,
                        "experience": experience,
                        "year_month": year_month,
                    }
                )
                if output["source_record_id"].isna().any():
                    raise RuntimeError(f"{year}年存在缺失来源记录ID")
                table = pa.Table.from_pandas(output, schema=OUTPUT_SCHEMA, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(temp_path, OUTPUT_SCHEMA, compression="zstd")
                writer.write_table(table)
                input_rows += len(output)
        finally:
            parquet.close()
            if writer is not None:
                writer.close()

        if not temp_path.is_file():
            raise RuntimeError(f"{year}年未生成临时特征文件")
        output_parquet = pq.ParquetFile(temp_path)
        output_rows = output_parquet.metadata.num_rows
        output_fields = output_parquet.schema_arrow.names
        output_parquet.close()
        if output_rows != input_rows or output_fields != OUTPUT_SCHEMA.names:
            raise RuntimeError(f"{year}年输出记录数或字段结构不一致")
        os.replace(temp_path, output_path)

        nonmissing_education = input_rows - education_missing
        nonmissing_experience = input_rows - experience_missing
        summary_rows.append(
            {
                "year": year,
                "input_rows": input_rows,
                "output_rows": output_rows,
                "education_raw_missing": education_missing,
                "education_unmapped": education_unmapped,
                "education_mapping_rate_nonmissing": round(
                    1 - education_unmapped / nonmissing_education, 8
                ) if nonmissing_education else None,
                "experience_raw_missing": experience_missing,
                "experience_unmapped": experience_unmapped,
                "experience_mapping_rate_nonmissing": round(
                    1 - experience_unmapped / nonmissing_experience, 8
                ) if nonmissing_experience else None,
                "year_month_missing": year_month_missing,
                "output_path": str(output_path),
            }
        )
        print(
            f"{year}: rows={output_rows:,} education_unmapped={education_unmapped:,} "
            f"experience_unmapped={experience_unmapped:,}",
            flush=True,
        )

    total_rows = sum(int(row["output_rows"]) for row in summary_rows)
    if total_rows != 5_235_461:
        raise RuntimeError(f"输出总记录数异常：{total_rows:,}")

    education_nonmissing = total_rows - sum(int(row["education_raw_missing"]) for row in summary_rows)
    experience_nonmissing = total_rows - sum(int(row["experience_raw_missing"]) for row in summary_rows)
    education_rate = 1 - sum(unmapped_education.values()) / education_nonmissing
    experience_rate = 1 - sum(unmapped_experience.values()) / experience_nonmissing
    if education_rate < 0.99 or experience_rate < 0.99:
        raise RuntimeError(
            f"映射覆盖率不足：education={education_rate:.4%}, experience={experience_rate:.4%}"
        )

    for path, old_snapshot in input_snapshots.items():
        if snapshot(Path(path)) != old_snapshot:
            raise RuntimeError(f"清洗输入在运行期间发生变化：{path}")

    write_csv(SUMMARY_PATH, summary_rows)
    unmapped_rows = [
        {"variable": "education", "raw_value": value, "count": count}
        for value, count in unmapped_education.most_common()
    ] + [
        {"variable": "experience", "raw_value": value, "count": count}
        for value, count in unmapped_experience.most_common()
    ]
    if not unmapped_rows:
        unmapped_rows = [{"variable": "", "raw_value": "", "count": 0}]
    write_csv(UNMAPPED_PATH, unmapped_rows)

    manifest = {
        "version": "confirmed_core_v1",
        "created_variables": ["wage_mid", "ln_wage", "education", "experience", "year_month"],
        "held_variables": ["firm_id", "occupation_id", "city_id", "skill_software", "skill_cognitive", "skill_social"],
        "input_rows": total_rows,
        "education_categories": list(EDUCATION_CATEGORIES),
        "experience_categories": list(EXPERIENCE_CATEGORIES),
        "education_mapping_rate_nonmissing": education_rate,
        "experience_mapping_rate_nonmissing": experience_rate,
        "summary_file": str(SUMMARY_PATH),
        "unmapped_file": str(UNMAPPED_PATH),
    }
    with open(output_root / "manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    print(f"EDUCATION_MAPPING_RATE={education_rate:.6%}")
    print(f"EXPERIENCE_MAPPING_RATE={experience_rate:.6%}")
    print(f"CONFIRMED_CORE_OUTPUT={output_root}")
    print("CONFIRMED_CORE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
