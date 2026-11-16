"""按项目组已确认口径构造基准回归核心变量 v2。

相较 v1，本版：
1. 把学历“其他/其它”归为“不限”；
2. 删除学历为“以上”“0”或误填工作地点的记录；
3. 新增初版 firm_id（六位上市公司股票代码）和 city_id（保守城市标准化）。

occupation_id 暂不构造。cleaned_v1 和 confirmed_core_v1 均保持只读。
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
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
SUMMARY_PATH = QC_ROOT / "confirmed_core_v2_summary.csv"
UNMAPPED_PATH = QC_ROOT / "confirmed_core_v2_unmapped_values.csv"
DELETED_PATH = QC_ROOT / "confirmed_core_v2_deleted_rows.csv"
CITY_MAPPING_PATH = QC_ROOT / "city_mapping_initial_v1.csv"
YEARS = tuple(range(2018, 2026))
BATCH_ROWS = 200_000
EXPECTED_INPUT_ROWS = 5_235_461
EXPECTED_DELETED_ROWS = 63
EXPECTED_OUTPUT_ROWS = EXPECTED_INPUT_ROWS - EXPECTED_DELETED_ROWS

EDUCATION_CATEGORIES = ("不限", "高中及以下", "大专", "本科", "硕士", "博士")
EXPERIENCE_CATEGORIES = ("不限/应届", "1年以内", "1—3年", "3—5年", "5年以上")
INVALID_EDUCATION_DELETE = {"以上", "0", "-山东-青岛-城阳区-"}

OUTPUT_SCHEMA = pa.schema(
    [
        pa.field("source_record_id", pa.string(), nullable=False),
        pa.field("wage_mid", pa.float64(), nullable=False),
        pa.field("ln_wage", pa.float64(), nullable=False),
        pa.field("education", pa.string()),
        pa.field("experience", pa.string()),
        pa.field("firm_id", pa.string()),
        pa.field("city_id", pa.string()),
        pa.field("year_month", pa.date32()),
    ]
)

PROVINCES = {
    "北京", "北京市", "天津", "天津市", "上海", "上海市", "重庆", "重庆市",
    "河北", "河北省", "山西", "山西省", "辽宁", "辽宁省", "吉林", "吉林省",
    "黑龙江", "黑龙江省", "江苏", "江苏省", "浙江", "浙江省", "安徽", "安徽省",
    "福建", "福建省", "江西", "江西省", "山东", "山东省", "河南", "河南省",
    "湖北", "湖北省", "湖南", "湖南省", "广东", "广东省", "海南", "海南省",
    "四川", "四川省", "贵州", "贵州省", "云南", "云南省", "陕西", "陕西省",
    "甘肃", "甘肃省", "青海", "青海省", "台湾", "台湾省",
    "内蒙古", "内蒙古自治区", "广西", "广西壮族自治区", "西藏", "西藏自治区",
    "宁夏", "宁夏回族自治区", "新疆", "新疆维吾尔自治区",
    "香港", "香港特别行政区", "澳门", "澳门特别行政区",
}
PROVINCE_PREFIXES = sorted(PROVINCES, key=len, reverse=True)
MUNICIPALITIES = {"北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆"}
SPECIAL_LOCALITIES = {
    "香港": "香港", "香港特别行政区": "香港",
    "澳门": "澳门", "澳门特别行政区": "澳门",
    "雄安新区": "雄安新区", "西咸新区": "西咸新区", "神农架林区": "神农架林区",
}
OVERSEAS_PATTERN = re.compile(r"海外|国外|境外|国际|美国|英国|日本|韩国|新加坡|澳大利亚|加拿大")
NONPLACE_PATTERN = re.compile(r"全国|不限|多地|异地|待定|其它|其他|若干|各地|就近|远程")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or list(rows[0])
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", "", str(value).strip())
    if not text or text.lower() in {"nan", "none", "null", "-", "--", "—"}:
        return None
    return text


@lru_cache(maxsize=None)
def map_education_text(text: str) -> str | None:
    if re.search(r"不限|无学历要求|无要求", text) or text in {"其他", "其它"}:
        return "不限"
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


CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def chinese_number_to_int(token: str) -> int:
    if token == "十":
        return 10
    if "十" in token:
        left, right = token.split("十", 1)
        return CHINESE_DIGITS.get(left, 1) * 10 + CHINESE_DIGITS.get(right, 0)
    value = 0
    digits = [CHINESE_DIGITS[char] for char in token if char in CHINESE_DIGITS]
    if not digits:
        raise ValueError(token)
    for digit in digits:
        value = value * 10 + digit
    return value


def replace_chinese_numbers(text: str) -> str:
    return re.sub(
        r"[零一二两三四五六七八九十]+",
        lambda match: str(chinese_number_to_int(match.group(0))),
        text,
    )


@lru_cache(maxsize=None)
def map_experience_text(text: str) -> str | None:
    if re.search(r"不限|应届|在校|在读|无需经验|无需工作经验|无工作经验|无经验|无要求|不要求经验|经验无要求|零经验", text):
        return "不限/应届"
    if text == "无" or re.search(r"^0年(以上|及以上)?$", text):
        return "不限/应届"
    normalized = replace_chinese_numbers(text).replace("个月", "月")
    if re.search(r"半年|6月|六个月|不满1年|不到1年", text) or re.search(r"1年(以内|以下)", normalized):
        return "1年以内"
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if match is None:
        return None
    years = float(match.group(1))
    if not math.isfinite(years) or years < 0:
        return None
    if years < 1:
        return "1年以内"
    if years < 3:
        return "1—3年"
    if years < 5:
        return "3—5年"
    return "5年以上"


def map_experience(value: object) -> tuple[str | None, str]:
    text = normalize_text(value)
    if text is None:
        return None, "missing"
    mapped = map_experience_text(text)
    return (mapped, "mapped") if mapped is not None else (None, "unmapped")


@lru_cache(maxsize=None)
def map_firm_text(text: str) -> str | None:
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text.replace(",", ""))
    if not match:
        return None
    number = int(match.group(1))
    if number < 0 or number > 999_999:
        return None
    return f"{number:06d}"


def map_firm(value: object) -> tuple[str | None, str]:
    text = normalize_text(value)
    if text is None:
        return None, "missing"
    mapped = map_firm_text(text)
    return (mapped, "mapped") if mapped is not None else (None, "unmapped")


def remove_province_prefix(text: str) -> str:
    for prefix in PROVINCE_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            remainder = text[len(prefix):].lstrip("-—_/·")
            # “吉林市”“海南州”等名称本身以省份简称开头，不能剥成“市/州”。
            if len(remainder) > 1:
                return remainder
    return text


@lru_cache(maxsize=None)
def map_city_text(text: str) -> tuple[str | None, str]:
    clean = text.replace("（", "(").replace("）", ")").strip("-—_/·,，;；")
    if OVERSEAS_PATTERN.search(clean):
        return "海外", "overseas"
    if NONPLACE_PATTERN.search(clean):
        return None, "withheld_non_specific"
    for municipality, mapped in MUNICIPALITIES.items():
        if clean.startswith(municipality):
            return mapped, "mapped_municipality"
    if clean in SPECIAL_LOCALITIES:
        return SPECIAL_LOCALITIES[clean], "mapped_special_locality"
    if clean in PROVINCES:
        return None, "withheld_province_only"

    parts = [item for item in re.split(r"[-—_/·]+", clean) if item]
    if len(parts) > 1:
        if parts[0] in PROVINCES:
            parts = parts[1:]
        if parts and len(parts) > 1 and re.search(r"区$|县$|旗$|新区$|开发区$|产业园$", parts[1]):
            clean = parts[0]
        elif len(parts) == 1:
            clean = parts[0]
        else:
            return None, "withheld_multiple_locations"

    clean = remove_province_prefix(clean)
    if re.search(r"[、,，;；|]", clean):
        return None, "withheld_multiple_locations"
    if "市" in clean:
        candidate = clean.split("市", 1)[0]
        candidate = remove_province_prefix(candidate)
        return (candidate, "mapped_city_suffix") if candidate else (None, "withheld_unresolved")
    if clean.endswith(("地区", "自治州", "盟", "林区")):
        return clean, "mapped_prefecture_like"
    if re.search(r"区$|县$|旗$|新区$|开发区$|产业园$", clean):
        return None, "withheld_county_or_district"
    if len(clean) <= 1 or re.search(r"招聘|办公|公司|项目|基地|岗位", clean):
        return None, "withheld_unresolved"
    return clean, "mapped_plain_name"


def map_city(value: object) -> tuple[str | None, str, str | None]:
    text = normalize_text(value)
    if text is None:
        return None, "missing", None
    mapped, status = map_city_text(text)
    return mapped, status, text


def snapshot(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def main() -> int:
    storage = load_json(STORAGE_CONFIG_PATH)
    input_root = Path(storage["curated_root"]) / "cleaned_v1"
    output_root = Path(storage["features_root"]) / "confirmed_core_v2"
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    deleted_rows: list[dict] = []
    unmapped_education: Counter[str] = Counter()
    unmapped_experience: Counter[str] = Counter()
    unmapped_firm: Counter[str] = Counter()
    city_raw_counts: Counter[str] = Counter()
    input_snapshots: dict[str, tuple[int, int]] = {}

    for year in YEARS:
        input_path = input_root / f"jobs_{year}_cleaned.parquet"
        output_path = output_root / f"jobs_{year}_confirmed_core.parquet"
        temp_path = output_path.with_suffix(".parquet.tmp")
        input_snapshots[str(input_path)] = snapshot(input_path)
        if temp_path.exists():
            temp_path.unlink()

        parquet = pq.ParquetFile(input_path)
        writer: pq.ParquetWriter | None = None
        input_rows = output_rows = deleted_count = 0
        education_missing = education_unmapped = 0
        experience_missing = experience_unmapped = 0
        firm_missing = firm_unmapped = city_missing = city_withheld = 0

        try:
            columns = ["来源记录ID", "月薪代表值", "学历要求", "要求经验", "关联股票代码",
                       "工作城市", "招聘发布日期", "企业名称", "招聘岗位"]
            for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=columns):
                frame = batch.to_pandas()
                input_rows += len(frame)
                normalized_education = frame["学历要求"].map(normalize_text)
                delete_mask = normalized_education.isin(INVALID_EDUCATION_DELETE)
                for _, row in frame.loc[delete_mask].iterrows():
                    raw = normalize_text(row["学历要求"])
                    reason = "学历为单独的‘以上’，含义不完整"
                    if raw == "0":
                        reason = "学历误填为0"
                    elif raw == "-山东-青岛-城阳区-":
                        reason = "学历字段误填工作地点"
                    deleted_rows.append({
                        "source_record_id": row["来源记录ID"], "year": year,
                        "company": row["企业名称"], "job_title": row["招聘岗位"],
                        "city_raw": row["工作城市"], "education_raw": row["学历要求"],
                        "experience_raw": row["要求经验"], "delete_reason": reason,
                    })
                deleted_count += int(delete_mask.sum())
                frame = frame.loc[~delete_mask].copy()

                wage_mid = pd.to_numeric(frame["月薪代表值"], errors="coerce").astype("float64")
                if wage_mid.isna().any() or (wage_mid <= 0).any():
                    raise RuntimeError(f"{year}年存在无效月薪代表值")

                education_result = frame["学历要求"].map(map_education)
                experience_result = frame["要求经验"].map(map_experience)
                firm_result = frame["关联股票代码"].map(map_firm)
                city_result = frame["工作城市"].map(map_city)

                education_status = education_result.map(lambda item: item[1])
                experience_status = experience_result.map(lambda item: item[1])
                firm_status = firm_result.map(lambda item: item[1])
                city_status = city_result.map(lambda item: item[1])
                education_missing += int((education_status == "missing").sum())
                education_unmapped += int((education_status == "unmapped").sum())
                experience_missing += int((experience_status == "missing").sum())
                experience_unmapped += int((experience_status == "unmapped").sum())
                firm_missing += int((firm_status == "missing").sum())
                firm_unmapped += int((firm_status == "unmapped").sum())
                city_missing += int((city_status == "missing").sum())
                city_withheld += int(city_status.str.startswith("withheld_").sum())

                for raw in frame.loc[education_status == "unmapped", "学历要求"]:
                    unmapped_education[str(raw).strip()] += 1
                for raw in frame.loc[experience_status == "unmapped", "要求经验"]:
                    unmapped_experience[str(raw).strip()] += 1
                for raw in frame.loc[firm_status == "unmapped", "关联股票代码"]:
                    unmapped_firm[str(raw).strip()] += 1
                for raw in city_result.map(lambda item: item[2]).dropna():
                    city_raw_counts[raw] += 1

                publish_date = pd.to_datetime(frame["招聘发布日期"], errors="coerce")
                output = pd.DataFrame({
                    "source_record_id": frame["来源记录ID"].astype("string"),
                    "wage_mid": wage_mid,
                    "ln_wage": np.log(wage_mid),
                    "education": education_result.map(lambda item: item[0]),
                    "experience": experience_result.map(lambda item: item[0]),
                    "firm_id": firm_result.map(lambda item: item[0]),
                    "city_id": city_result.map(lambda item: item[0]),
                    "year_month": publish_date.dt.to_period("M").dt.to_timestamp(),
                })
                if output["source_record_id"].isna().any():
                    raise RuntimeError(f"{year}年存在缺失来源记录ID")
                table = pa.Table.from_pandas(output, schema=OUTPUT_SCHEMA, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(temp_path, OUTPUT_SCHEMA, compression="zstd")
                writer.write_table(table)
                output_rows += len(output)
        finally:
            parquet.close()
            if writer is not None:
                writer.close()

        check = pq.ParquetFile(temp_path)
        if check.metadata.num_rows != output_rows or check.schema_arrow.names != OUTPUT_SCHEMA.names:
            raise RuntimeError(f"{year}年输出行数或字段结构异常")
        check.close()
        if input_rows != output_rows + deleted_count:
            raise RuntimeError(f"{year}年记录不守恒")
        os.replace(temp_path, output_path)
        summary_rows.append({
            "year": year, "input_rows": input_rows, "deleted_invalid_education": deleted_count,
            "output_rows": output_rows, "education_raw_missing": education_missing,
            "education_unmapped": education_unmapped, "experience_raw_missing": experience_missing,
            "experience_unmapped": experience_unmapped, "firm_missing": firm_missing,
            "firm_unmapped": firm_unmapped, "city_raw_missing": city_missing,
            "city_withheld_initial_rule": city_withheld, "output_path": str(output_path),
        })
        print(f"{year}: input={input_rows:,} deleted={deleted_count:,} output={output_rows:,}", flush=True)

    total_input = sum(row["input_rows"] for row in summary_rows)
    total_output = sum(row["output_rows"] for row in summary_rows)
    if total_input != EXPECTED_INPUT_ROWS or len(deleted_rows) != EXPECTED_DELETED_ROWS or total_output != EXPECTED_OUTPUT_ROWS:
        raise RuntimeError(
            f"总量异常：input={total_input:,}, deleted={len(deleted_rows):,}, output={total_output:,}"
        )
    if unmapped_education or unmapped_firm:
        raise RuntimeError(f"存在未处理的学历或股票代码：education={unmapped_education}, firm={unmapped_firm}")
    for path, old_snapshot in input_snapshots.items():
        if snapshot(Path(path)) != old_snapshot:
            raise RuntimeError(f"输入文件在运行期间发生变化：{path}")

    total_row = {"year": "合计"}
    for name in summary_rows[0]:
        if name not in {"year", "output_path"}:
            total_row[name] = sum(int(row[name]) for row in summary_rows)
    total_row["output_path"] = str(output_root)
    write_csv(SUMMARY_PATH, summary_rows + [total_row])
    write_csv(DELETED_PATH, deleted_rows)

    unmapped_rows = [
        {"variable": variable, "raw_value": raw, "count": count}
        for variable, counter in (("education", unmapped_education), ("experience", unmapped_experience),
                                  ("firm_id", unmapped_firm))
        for raw, count in counter.most_common()
    ]
    if not unmapped_rows:
        unmapped_rows = [{"variable": "", "raw_value": "", "count": 0}]
    write_csv(UNMAPPED_PATH, unmapped_rows)

    city_rows = []
    for raw, count in city_raw_counts.most_common():
        mapped, status = map_city_text(raw)
        city_rows.append({"city_raw": raw, "city_id_initial": mapped or "", "mapping_status": status, "count": count})
    write_csv(CITY_MAPPING_PATH, city_rows)

    manifest = {
        "version": "confirmed_core_v2",
        "input_version": "cleaned_v1",
        "input_rows": total_input,
        "deleted_rows": len(deleted_rows),
        "output_rows": total_output,
        "created_variables": OUTPUT_SCHEMA.names[1:],
        "held_variables": ["occupation_id", "skill_software", "skill_cognitive", "skill_social", "ai_skill"],
        "education_rule": "其他/其它归为不限；以上、0、误填工作地点的记录删除",
        "firm_id_rule_version": "listed_company_code_initial_v1",
        "firm_id_limitation": "六位股票代码表示上市公司集团层级，不等于实际招聘企业；后期需构造更细企业ID",
        "city_id_rule_version": "conservative_city_text_initial_v1",
        "city_id_limitation": "纯省份、无法归属的区县和多地信息暂不映射；后期需用行政区划表和人工复核完善",
        "summary_file": str(SUMMARY_PATH),
        "deleted_evidence_file": str(DELETED_PATH),
        "city_mapping_file": str(CITY_MAPPING_PATH),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CONFIRMED_CORE_V2_OUTPUT={output_root}")
    print("CONFIRMED_CORE_V2_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
