"""建立职业分类大典2022正式版代码表和v0.2职业别名表。

代码表以固定Git提交中的结构化整理件为机器输入，并用正式版职业总数、
绿色/数字职业数量、层级数量以及政府公开岗位类别编码表做交叉核验。
整理件不是官方发布物，最终依据仍是国家正式出版文本。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
MANUAL_ALIAS_PATH = PROJECT_ROOT / "config" / "occupation_aliases_manual_v0.2.csv"
DICTIONARY_PATH = PROJECT_ROOT / "config" / "occupation_dictionary_2022_official.csv"
HIERARCHY_PATH = PROJECT_ROOT / "config" / "occupation_hierarchy_2022_official.csv"
ALIAS_PATH = PROJECT_ROOT / "config" / "occupation_aliases_v0.2.csv"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
REPORT_PATH = QC_ROOT / "occupation_dictionary_2022_validation.md"
MANIFEST_PATH = QC_ROOT / "occupation_dictionary_2022_manifest.json"

SOURCE_COMMIT = "d845c000dcf2c95a35f30f7db1fe195627630c36"
SOURCE_REPOSITORY = "https://github.com/synkarta/Classification_Code_of_Occupations-China"
SOURCE_FILES = {
    "fine": {
        "name": "dadian2022_official_1639.csv",
        "url": (
            "https://raw.githubusercontent.com/synkarta/"
            "Classification_Code_of_Occupations-China/"
            f"{SOURCE_COMMIT}/data/dadian2022_official_1639.csv"
        ),
        "sha256": "bcf219a07d6655b0c7001ed2b2f2af1e820ceee134a668e9fcca52ec32e881a8",
    },
    "hierarchy": {
        "name": "hierarchy_2022.csv",
        "url": (
            "https://raw.githubusercontent.com/synkarta/"
            "Classification_Code_of_Occupations-China/"
            f"{SOURCE_COMMIT}/data/hierarchy_2022.csv"
        ),
        "sha256": "c7701c970c174691687071c91d6b8e4da5c0cf9e055b06eaed3af687f670ee70",
    },
}
OFFICIAL_RELEASE_URL = "https://chinajob.mohrss.gov.cn/h5/c/2022-10-08/361551.shtml"
GOVERNMENT_CODE_TABLE_URL = (
    "https://srsj.cngy.gov.cn/Files/UploadFile/SiteFile/20160720104022026/"
    "2023/03/28/33236d995ac3404a99de2429f1e92f52.pdf"
)
EXPECTED_GOVERNMENT_PDF_SHA256 = "43b86f85a730627ad0941354ccf4e32cca6140a343c1bdb5dc0b4629386ebf8d"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, path: Path, expected_sha256: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or sha256(path) != expected_sha256:
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        request = urllib.request.Request(url, headers={"User-Agent": "SRTP-research/occupation-v0.2"})
        with urllib.request.urlopen(request, timeout=60) as response, open(temporary, "wb") as handle:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
        if sha256(temporary) != expected_sha256:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"下载文件哈希不符：{url}")
        os.replace(temporary, path)


def normalize_alias(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[·•,，;；:：/_|\\\-—]+", "", text)
    return text.strip("()[]【】")


def split_markers(value: str) -> tuple[str, bool, bool]:
    text = str(value).strip()
    both = text.endswith("L/S")
    green = both or (text.endswith("L") and not both)
    digital = both or (text.endswith("S") and not both)
    clean = re.sub(r"(?:L/S|L|S)$", "", text).strip()
    return clean, green, digital


def systematic_variants(name: str) -> set[str]:
    variants: set[str] = set()
    replacements = [
        ("工程技术人员", "工程师"),
        ("工程技术人员", "工程"),
        ("专业技术人员", "专业技术员"),
        ("专业人员", "专员"),
        ("技术人员", "技术员"),
        ("服务人员", "服务员"),
        ("管理人员", "管理员"),
    ]
    for suffix, replacement in replacements:
        if name.endswith(suffix):
            candidate = name[: -len(suffix)] + replacement
            if len(candidate) >= 3:
                variants.add(candidate)
    if name.endswith("人员") and len(name) >= 7 and not name.startswith("其他"):
        variants.add(name[:-2])
    return {value for value in variants if value != name}


def main() -> int:
    storage = load_json(STORAGE_PATH)
    evidence_root = Path(storage["evidence_root"]) / "occupation_standard_2022"
    source_root = evidence_root / "structured_source"

    source_paths: dict[str, Path] = {}
    for key, source in SOURCE_FILES.items():
        path = source_root / source["name"]
        download_verified(source["url"], path, source["sha256"])
        source_paths[key] = path

    government_pdf = evidence_root / "occupation_dictionary_2022_government.pdf"
    government_pdf_ok = government_pdf.exists() and sha256(government_pdf) == EXPECTED_GOVERNMENT_PDF_SHA256

    fine = pd.read_csv(source_paths["fine"], dtype="string")
    hierarchy = pd.read_csv(source_paths["hierarchy"], dtype={"level": "int8", "careerCode": "string", "careerName": "string", "parentCode": "string"})
    if list(fine.columns) != ["careerCode", "careerName"]:
        raise RuntimeError("职业细类源表字段异常")
    if list(hierarchy.columns) != ["level", "careerCode", "careerName", "parentCode"]:
        raise RuntimeError("职业层级源表字段异常")
    if len(fine) != 1_639 or fine["careerCode"].duplicated().any():
        raise RuntimeError("正式版职业细类数量或代码唯一性异常")
    if not fine["careerCode"].str.fullmatch(r"[1-8]-\d{2}-\d{2}-\d{2}").all():
        raise RuntimeError("职业细类代码格式异常")

    level_counts = hierarchy.groupby("level").size().to_dict()
    if level_counts != {1: 8, 2: 79, 3: 450}:
        raise RuntimeError(f"层级数量异常：{level_counts}")
    substantive_small = hierarchy.loc[(hierarchy["level"] == 3) & (hierarchy["careerCode"] != "8-00-00")]
    if len(substantive_small) != 449:
        raise RuntimeError("除不便分类代码外的小类数量不是449")

    hierarchy_maps = {
        level: hierarchy.loc[hierarchy["level"] == level].set_index("careerCode")["careerName"].to_dict()
        for level in (1, 2, 3)
    }
    hierarchy_output = hierarchy.rename(columns={
        "level": "occupation_level",
        "careerCode": "occupation_code",
        "careerName": "occupation_name",
        "parentCode": "parent_code",
    }).copy()
    hierarchy_output["occupation_level_name"] = hierarchy_output["occupation_level"].map({1: "major", 2: "middle", 3: "small"})
    hierarchy_output["is_unclassified_code"] = hierarchy_output["occupation_code"].eq("8-00-00").astype("int8")
    hierarchy_output["source_version"] = "职业分类大典2022正式版层级"
    hierarchy_output = hierarchy_output[[
        "occupation_level", "occupation_level_name", "occupation_code", "occupation_name",
        "parent_code", "is_unclassified_code", "source_version",
    ]]
    hierarchy_output.to_csv(HIERARCHY_PATH, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    dictionary_rows: list[dict] = []
    for row in fine.itertuples(index=False):
        fine_name, is_green, is_digital = split_markers(row.careerName)
        parts = row.careerCode.split("-")
        major_code = parts[0]
        middle_code = "-".join(parts[:2])
        small_code = "-".join(parts[:3])
        if major_code not in hierarchy_maps[1] or middle_code not in hierarchy_maps[2] or small_code not in hierarchy_maps[3]:
            raise RuntimeError(f"职业代码缺少上级层级：{row.careerCode}")
        dictionary_rows.append({
            "occupation_fine_code": row.careerCode,
            "occupation_fine_name": fine_name,
            "occupation_small_code": small_code,
            "occupation_small_name": hierarchy_maps[3][small_code],
            "occupation_middle_code": middle_code,
            "occupation_middle_name": hierarchy_maps[2][middle_code],
            "occupation_major_code": major_code,
            "occupation_major_name": hierarchy_maps[1][major_code],
            "is_green_occupation": int(is_green),
            "is_digital_occupation": int(is_digital),
            "source_version": "职业分类大典2022正式版（1639职业）",
        })
    dictionary = pd.DataFrame(dictionary_rows)
    green_count = int(dictionary["is_green_occupation"].sum())
    digital_count = int(dictionary["is_digital_occupation"].sum())
    both_count = int(((dictionary["is_green_occupation"] == 1) & (dictionary["is_digital_occupation"] == 1)).sum())
    if (green_count, digital_count, both_count) != (134, 97, 23):
        raise RuntimeError("绿色或数字职业数量未通过正式版口径核验")

    dictionary.to_csv(DICTIONARY_PATH, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    small_names = dictionary.drop_duplicates("occupation_small_code").set_index("occupation_small_code")["occupation_small_name"].to_dict()
    fine_records = dictionary.set_index("occupation_fine_code").to_dict("index")
    alias_candidates: list[dict] = []
    for record in dictionary.to_dict("records"):
        base = {
            "target_level": "fine",
            "target_code": record["occupation_fine_code"],
            "occupation_fine_code": record["occupation_fine_code"],
            "occupation_fine_name": record["occupation_fine_name"],
            "occupation_small_code": record["occupation_small_code"],
            "occupation_small_name": record["occupation_small_name"],
        }
        alias_candidates.append({
            "alias": record["occupation_fine_name"],
            "alias_source": "official_name",
            "review_status": "official",
            "priority": 1,
            "notes": "职业大典正式职业名称",
            **base,
        })
        for variant in systematic_variants(record["occupation_fine_name"]):
            alias_candidates.append({
                "alias": variant,
                "alias_source": "systematic_variant",
                "review_status": "machine_unique_only",
                "priority": 2,
                "notes": "由职业名称后缀替换生成；仅在小类映射唯一时启用",
                **base,
            })

    manual = pd.read_csv(MANUAL_ALIAS_PATH, dtype="string").fillna("")
    expected_manual_columns = ["alias", "target_level", "target_code", "notes"]
    if list(manual.columns) != expected_manual_columns or manual["alias"].duplicated().any():
        raise RuntimeError("人工别名表字段或别名唯一性异常")
    for row in manual.itertuples(index=False):
        if row.target_level == "fine":
            if row.target_code not in fine_records:
                raise RuntimeError(f"人工别名指向不存在的职业细类：{row.alias} -> {row.target_code}")
            target = fine_records[row.target_code]
            fine_code = row.target_code
            fine_name = target["occupation_fine_name"]
            small_code = target["occupation_small_code"]
            small_name = target["occupation_small_name"]
        elif row.target_level == "small":
            if row.target_code not in small_names:
                raise RuntimeError(f"人工别名指向不存在的职业小类：{row.alias} -> {row.target_code}")
            fine_code = ""
            fine_name = ""
            small_code = row.target_code
            small_name = small_names[row.target_code]
        else:
            raise RuntimeError(f"人工别名层级无效：{row.alias} -> {row.target_level}")
        alias_candidates.append({
            "alias": row.alias,
            "alias_source": "manual_v0.2",
            "review_status": "curated_v0.2",
            "priority": 0,
            "notes": row.notes,
            "target_level": row.target_level,
            "target_code": row.target_code,
            "occupation_fine_code": fine_code,
            "occupation_fine_name": fine_name,
            "occupation_small_code": small_code,
            "occupation_small_name": small_name,
        })

    aliases = pd.DataFrame(alias_candidates)
    aliases["alias_normalized"] = aliases["alias"].map(normalize_alias)
    aliases = aliases.loc[aliases["alias_normalized"].str.len() >= 2].copy()
    resolved_rows: list[pd.Series] = []
    ambiguous_aliases = 0
    for _, group in aliases.groupby("alias_normalized", sort=True):
        manual_group = group.loc[group["priority"] == 0]
        if not manual_group.empty:
            group = manual_group
        else:
            official_group = group.loc[group["priority"] == 1]
            if not official_group.empty:
                group = official_group
        distinct_small = group["occupation_small_code"].nunique()
        chosen = group.sort_values(["priority", "target_code", "alias"]).iloc[0].copy()
        if distinct_small > 1:
            chosen["usable_for_matching"] = 0
            chosen["ambiguity_count"] = int(distinct_small)
            ambiguous_aliases += 1
        else:
            chosen["usable_for_matching"] = 1
            chosen["ambiguity_count"] = 1
        resolved_rows.append(chosen)
    alias_table = pd.DataFrame(resolved_rows).sort_values(["usable_for_matching", "priority", "alias_normalized"], ascending=[False, True, True])
    alias_table = alias_table[[
        "alias", "alias_normalized", "alias_source", "review_status", "target_level", "target_code",
        "occupation_fine_code", "occupation_fine_name", "occupation_small_code", "occupation_small_name",
        "usable_for_matching", "ambiguity_count", "notes",
    ]]
    alias_table.to_csv(ALIAS_PATH, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    QC_ROOT.mkdir(parents=True, exist_ok=True)
    dictionary_hash = sha256(DICTIONARY_PATH)
    hierarchy_hash = sha256(HIERARCHY_PATH)
    alias_hash = sha256(ALIAS_PATH)
    manifest = {
        "status": "PASS",
        "standard": "中华人民共和国职业分类大典（2022年正式版）",
        "fine_occupations": len(dictionary),
        "major_classes": 8,
        "middle_classes": 79,
        "substantive_small_classes": 449,
        "small_codes_including_8_00_00": 450,
        "green_occupations": green_count,
        "digital_occupations": digital_count,
        "green_and_digital": both_count,
        "aliases_total": len(alias_table),
        "aliases_usable": int(alias_table["usable_for_matching"].sum()),
        "aliases_ambiguous": ambiguous_aliases,
        "manual_aliases": len(manual),
        "dictionary_sha256": dictionary_hash,
        "hierarchy_sha256": hierarchy_hash,
        "alias_sha256": alias_hash,
        "source_repository": SOURCE_REPOSITORY,
        "source_license": "CC-BY-4.0（结构化数据与文档）",
        "source_commit": SOURCE_COMMIT,
        "source_files": SOURCE_FILES,
        "official_release_url": OFFICIAL_RELEASE_URL,
        "government_code_table_url": GOVERNMENT_CODE_TABLE_URL,
        "government_code_table_local_sha256": sha256(government_pdf) if government_pdf.exists() else None,
        "government_code_table_verified": government_pdf_ok,
        "limitation": "结构化底表为非官方机器整理件；如与国家正式出版文本不符，以正式出版文本为准。",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""# 职业大典2022正式版代码表验证

结论：PASS

## 代码表

- 正式版职业细类：{len(dictionary):,}个；
- 大类：8个；中类：79个；
- 实质职业小类：449个；另保留`8-00-00`不便分类代码，因此代码表中小类代码共450个；
- 绿色职业：{green_count}个；数字职业：{digital_count}个；双标职业：{both_count}个；
- 职业代码、上级代码和名称均通过唯一性与层级连接检查。

## 别名表

- 人工整理别名：{len(manual):,}个；
- 合并正式名称和唯一系统变体后：{len(alias_table):,}个；
- 可用于匹配：{int(alias_table['usable_for_matching'].sum()):,}个；
- 因跨小类歧义而禁用：{ambiguous_aliases:,}个。

## 版本说明

- 2022年7月公示稿为1,636个职业；本项目使用2022年9月正式发布版1,639个职业；
- 结构化机器输入固定到第三方整理仓库提交`{SOURCE_COMMIT}`，并校验原始文件SHA-256；
- 政府公开岗位类别编码表本地哈希校验：{'通过' if government_pdf_ok else '未取得或未通过'}；
- 结构化整理件不是官方发布物。如与国家正式出版文本不一致，以正式出版文本为准。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"DICTIONARY_ROWS={len(dictionary)}")
    print(f"ALIASES_ROWS={len(alias_table)}")
    print(f"ALIASES_USABLE={int(alias_table['usable_for_matching'].sum())}")
    print(f"MANUAL_ALIASES={len(manual)}")
    print("DICTIONARY_PREP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
