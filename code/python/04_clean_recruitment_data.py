"""按项目组确认的规则清洗2018—2025年招聘数据。

输入为23字段标准化Parquet。脚本不修改原始CSV，也不覆盖标准化输入。
输出包括：年度清洗Parquet、删除记录证据、年度流程统计和交接说明所需的验证结果。
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_PATH = PROJECT_ROOT / "config" / "cleaning_rules.json"
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "cleaning_v1_summary.csv"
ACTION_PATH = PROJECT_ROOT / "outputs" / "qc" / "cleaning_v1_actions.csv"
VALIDATION_PATH = PROJECT_ROOT / "outputs" / "qc" / "cleaning_v1_validation.md"
YEARS = tuple(range(2018, 2026))
BLANK_MARKERS = ("", "nan", "none", "null", "na", "n/a", ".", "-", "--", "—")


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def blank_normalized(column: str) -> str:
    markers = ", ".join(sql_literal(item) for item in BLANK_MARKERS)
    return (
        f"CASE WHEN lower(trim(coalesce(cast(\"{column}\" AS VARCHAR), ''))) "
        f"IN ({markers}) THEN NULL ELSE trim(cast(\"{column}\" AS VARCHAR)) END"
    )


def salary_numeric(column: str) -> str:
    normalized = blank_normalized(column)
    return f"try_cast(replace(({normalized}), ',', '') AS DOUBLE)"


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rules = load_json(CONFIG_PATH)
    storage = load_json(STORAGE_CONFIG_PATH)
    fields = rules["official_fields"]
    if len(fields) != 23:
        raise RuntimeError("正式字段必须恰好为23个")

    input_root = Path(storage["curated_root"]) / "schema_23fields_v1"
    output_root = Path(storage["curated_root"]) / "cleaned_v1"
    evidence_root = Path(storage["evidence_root"]) / "cleaning_v1"
    temp_root = Path(storage["duckdb_temp"])
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    (temp_root / "spill_cleaning_v1").mkdir(parents=True, exist_ok=True)

    input_files = [input_root / f"jobs_{year}_23fields.parquet" for year in YEARS]
    missing_files = [str(path) for path in input_files if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(f"缺少标准化输入：{missing_files}")

    input_snapshots = {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in input_files}
    database_path = temp_root / "srtp_cleaning_v1.duckdb"
    if database_path.exists():
        database_path.unlink()
    con = duckdb.connect(str(database_path))
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='12GB'")
    con.execute(f"PRAGMA temp_directory={sql_literal(temp_root / 'spill_cleaning_v1')}")

    input_glob = sql_literal(input_root / "jobs_*_23fields.parquet")
    normalized_columns = ",\n            ".join(
        f"{blank_normalized(name)} AS \"{name}_规范\"" for name in fields
    )
    completeness = " + ".join(
        f"CASE WHEN \"{name}_规范\" IS NULL THEN 0 ELSE 1 END" for name in fields
    )

    create_sql = f"""
    CREATE TABLE cleaning_decisions AS
    WITH source AS (
        SELECT
            *,
            regexp_extract(filename, 'jobs_([0-9]{{4}})_23fields\\.parquet$', 1)::INTEGER AS source_year,
            filename AS source_file,
            file_row_number::BIGINT AS source_row_number,
            concat(regexp_extract(filename, 'jobs_([0-9]{{4}})_23fields\\.parquet$', 1), '-',
                   lpad(cast(file_row_number + 1 AS VARCHAR), 9, '0')) AS source_record_id
        FROM read_parquet({input_glob}, filename=true, file_row_number=true, union_by_name=true)
    ),
    normalized AS (
        SELECT
            source_year, source_file, source_row_number, source_record_id,
            {normalized_columns},
            {salary_numeric('最低月薪')} AS salary_low_num,
            {salary_numeric('最高月薪')} AS salary_high_num
        FROM source
    ),
    assessed AS (
        SELECT *,
            CASE WHEN salary_low_num > 0 THEN 1 ELSE 0 END
              + CASE WHEN salary_high_num > 0 THEN 1 ELSE 0 END AS salary_valid_count,
            ({completeness}) AS nonblank_field_count,
            try_cast("招聘发布日期_规范" AS DATE) AS publish_date_parsed,
            try_cast("招聘结束日期_规范" AS DATE) AS end_date_parsed
        FROM normalized
    ),
    fixed AS (
        SELECT *,
            salary_valid_count = 2 AND salary_low_num > salary_high_num AS salary_bounds_swapped,
            publish_date_parsed IS NOT NULL AND end_date_parsed IS NOT NULL
                AND end_date_parsed < publish_date_parsed AS date_order_swapped,
            CASE
                WHEN salary_low_num > 0 AND salary_high_num > 0 AND salary_low_num > salary_high_num THEN salary_high_num
                WHEN salary_low_num > 0 THEN salary_low_num
                ELSE NULL
            END AS salary_low_clean,
            CASE
                WHEN salary_low_num > 0 AND salary_high_num > 0 AND salary_low_num > salary_high_num THEN salary_low_num
                WHEN salary_high_num > 0 THEN salary_high_num
                ELSE NULL
            END AS salary_high_clean,
            CASE
                WHEN publish_date_parsed IS NOT NULL AND end_date_parsed IS NOT NULL
                     AND end_date_parsed < publish_date_parsed THEN end_date_parsed
                ELSE publish_date_parsed
            END AS publish_date_clean,
            CASE
                WHEN publish_date_parsed IS NOT NULL AND end_date_parsed IS NOT NULL
                     AND end_date_parsed < publish_date_parsed THEN publish_date_parsed
                ELSE end_date_parsed
            END AS end_date_clean
        FROM assessed
    ),
    keyed AS (
        SELECT *,
            sha256(concat_ws(chr(31),
                coalesce("企业名称_规范", '∅'),
                coalesce("招聘岗位_规范", '∅'),
                coalesce("工作城市_规范", '∅'),
                coalesce(cast(publish_date_clean AS VARCHAR), coalesce("招聘发布日期_规范", '∅')),
                coalesce("职位描述_规范", '∅')
            )) AS content_id
        FROM fixed
        WHERE salary_valid_count > 0
    ),
    ranked AS (
        SELECT *,
            count(*) OVER (PARTITION BY content_id) AS duplicate_group_size,
            row_number() OVER (
                PARTITION BY content_id
                ORDER BY salary_valid_count DESC,
                         ("学历要求_规范" IS NOT NULL) DESC,
                         (end_date_clean IS NOT NULL) DESC,
                         nonblank_field_count DESC,
                         source_year ASC,
                         source_row_number ASC
            ) AS duplicate_rank
        FROM keyed
    )
    SELECT
        n.source_year, n.source_file, n.source_row_number, n.source_record_id,
        r.content_id,
        n.salary_valid_count,
        coalesce(r.salary_bounds_swapped, false) AS salary_bounds_swapped,
        coalesce(r.date_order_swapped, false) AS date_order_swapped,
        r.salary_low_clean, r.salary_high_clean,
        CASE
            WHEN n.salary_valid_count = 2 THEN (r.salary_low_clean + r.salary_high_clean) / 2.0
            WHEN n.salary_valid_count = 1 THEN coalesce(r.salary_low_clean, r.salary_high_clean)
            ELSE NULL
        END AS salary_representative,
        CASE
            WHEN n.salary_valid_count = 2 THEN '两端点均有效，取均值'
            WHEN r.salary_low_clean IS NOT NULL THEN '仅最低月薪有效，保留该值'
            WHEN r.salary_high_clean IS NOT NULL THEN '仅最高月薪有效，保留该值'
            ELSE '两个工资端点均无效'
        END AS salary_method,
        r.publish_date_clean, r.end_date_clean,
        n."学历要求_规范" IS NULL AS education_missing,
        r.end_date_clean IS NULL AS end_date_missing,
        coalesce(r.duplicate_group_size, 0) AS duplicate_group_size,
        r.duplicate_rank,
        n.salary_valid_count = 0 AS delete_salary_invalid,
        n.salary_valid_count > 0 AND r.duplicate_rank > 1 AS delete_duplicate,
        n.salary_valid_count > 0 AND r.duplicate_rank = 1 AS keep_record
    FROM assessed n
    LEFT JOIN ranked r
      ON n.source_file = r.source_file AND n.source_row_number = r.source_row_number
    """
    print("正在建立全样本清洗决策表……", flush=True)
    con.execute(create_sql)
    total_decisions = con.execute("SELECT count(*) FROM cleaning_decisions").fetchone()[0]
    if total_decisions != 6_050_088:
        raise RuntimeError(f"输入总记录数异常：{total_decisions:,}")

    deleted_temp = evidence_root / "deleted_records.parquet.tmp"
    deleted_output = evidence_root / "deleted_records.parquet"
    if deleted_temp.exists():
        deleted_temp.unlink()
    con.execute(
        f"""COPY (
            SELECT source_record_id, source_year, source_file, source_row_number, content_id,
                   CASE WHEN delete_salary_invalid THEN '两个工资端点均无效'
                        WHEN delete_duplicate THEN '重复广告，仅保留优先记录' END AS delete_reason,
                   salary_valid_count, duplicate_group_size, duplicate_rank
            FROM cleaning_decisions
            WHERE NOT keep_record
        ) TO {sql_literal(deleted_temp)} (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    os.replace(deleted_temp, deleted_output)

    output_fields = []
    for name in fields:
        if name == "招聘发布年份":
            output_fields.append(
                'coalesce(year(d.publish_date_clean), try_cast(s."招聘发布年份" AS INTEGER)) AS "招聘发布年份"'
            )
        elif name == "招聘结束年份":
            output_fields.append(
                'coalesce(year(d.end_date_clean), try_cast(s."招聘结束年份" AS INTEGER)) AS "招聘结束年份"'
            )
        elif name == "最低月薪":
            output_fields.append('d.salary_low_clean AS "最低月薪"')
        elif name == "最高月薪":
            output_fields.append('d.salary_high_clean AS "最高月薪"')
        elif name == "招聘发布日期":
            output_fields.append('d.publish_date_clean AS "招聘发布日期"')
        elif name == "招聘结束日期":
            output_fields.append('d.end_date_clean AS "招聘结束日期"')
        elif name == "学历要求":
            output_fields.append(f'{blank_normalized("学历要求")} AS "学历要求"')
        else:
            output_fields.append(f's."{name}"')
    output_select = ",\n                ".join(output_fields)

    print("正在写出年度清洗数据……", flush=True)
    for year in YEARS:
        source_path = input_root / f"jobs_{year}_23fields.parquet"
        temp_path = output_root / f"jobs_{year}_cleaned.parquet.tmp"
        output_path = output_root / f"jobs_{year}_cleaned.parquet"
        if temp_path.exists():
            temp_path.unlink()
        con.execute(
            f"""COPY (
                SELECT
                {output_select},
                d.source_record_id AS "来源记录ID",
                d.content_id AS "内容ID",
                d.salary_representative AS "月薪代表值",
                d.salary_method AS "工资清洗方式",
                d.salary_bounds_swapped AS "工资上下限已交换",
                d.date_order_swapped AS "日期顺序已交换",
                d.education_missing AS "学历要求缺失",
                d.end_date_missing AS "招聘结束日期缺失",
                d.duplicate_group_size AS "重复组记录数",
                s."最低月薪" AS "最低月薪_原始",
                s."最高月薪" AS "最高月薪_原始",
                s."招聘发布日期" AS "招聘发布日期_原始",
                s."招聘结束日期" AS "招聘结束日期_原始",
                s."学历要求" AS "学历要求_原始"
                FROM read_parquet({sql_literal(source_path)}, file_row_number=true) s
                JOIN cleaning_decisions d ON d.source_year = {year}
                    AND d.source_row_number = s.file_row_number
                WHERE d.keep_record
                ORDER BY s.file_row_number
            ) TO {sql_literal(temp_path)} (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
        os.replace(temp_path, output_path)
        print(f"{year}: 已写出 {pq.ParquetFile(output_path).metadata.num_rows:,} 条", flush=True)

    summary_query = """
        SELECT source_year AS year,
               count(*) AS input_rows,
               sum(delete_salary_invalid::INTEGER) AS deleted_salary_invalid,
               sum(delete_duplicate::INTEGER) AS deleted_duplicates,
               sum(keep_record::INTEGER) AS output_rows,
               sum((keep_record AND salary_bounds_swapped)::INTEGER) AS salary_bounds_swapped,
               sum((keep_record AND date_order_swapped)::INTEGER) AS date_order_swapped,
               sum((keep_record AND salary_valid_count = 1)::INTEGER) AS one_valid_salary_endpoint,
               sum((keep_record AND education_missing)::INTEGER) AS education_missing_kept,
               sum((keep_record AND end_date_missing)::INTEGER) AS end_date_missing_kept
        FROM cleaning_decisions
        GROUP BY source_year
        ORDER BY source_year
    """
    summary_columns = [item[0] for item in con.execute(summary_query).description]
    summary_rows = [dict(zip(summary_columns, row)) for row in con.execute(summary_query).fetchall()]
    total_row = {"year": "合计"}
    for name in summary_columns[1:]:
        total_row[name] = sum(int(row[name]) for row in summary_rows)
    summary_rows.append(total_row)
    write_csv(SUMMARY_PATH, summary_rows)

    action_rows = [
        {"problem": "重复广告", "rule": "核心内容相同", "action": "按完整度排序后只保留一条", "trace_field": "内容ID、重复组记录数"},
        {"problem": "工资上下限颠倒", "rule": "最低月薪>最高月薪，且两端点均>0", "action": "交换上下限", "trace_field": "工资上下限已交换"},
        {"problem": "日期顺序颠倒", "rule": "招聘结束日期<招聘发布日期", "action": "交换发布日期与结束日期", "trace_field": "日期顺序已交换"},
        {"problem": "结束日期缺失", "rule": "结束日期为空或不能解析", "action": "保留并标缺失", "trace_field": "招聘结束日期缺失"},
        {"problem": "学历要求缺失", "rule": "学历字段为空或标准缺失标记", "action": "保留并标缺失", "trace_field": "学历要求缺失"},
        {"problem": "两个工资端点均无效", "rule": "两端点均非数值、缺失或<=0", "action": "删除记录", "trace_field": "删除证据.delete_reason"},
        {"problem": "只有一个工资端点有效", "rule": "恰有一个端点为数值且>0", "action": "保留有效端点，另一个设为缺失", "trace_field": "工资清洗方式、月薪代表值"},
    ]
    write_csv(ACTION_PATH, action_rows)

    final_rows = sum(int(row["output_rows"]) for row in summary_rows[:-1])
    deleted_rows = total_decisions - final_rows
    evidence_rows = pq.ParquetFile(deleted_output).metadata.num_rows
    if evidence_rows != deleted_rows:
        raise RuntimeError(f"删除证据记录数不一致：{evidence_rows:,} != {deleted_rows:,}")
    if final_rows + deleted_rows != total_decisions:
        raise RuntimeError("输入、保留与删除记录数不守恒")

    for path, old_snapshot in input_snapshots.items():
        stat = Path(path).stat()
        if (stat.st_size, stat.st_mtime_ns) != old_snapshot:
            raise RuntimeError(f"标准化输入在运行期间发生变化：{path}")

    manifest = {
        "cleaning_version": rules["cleaning_version"],
        "input_root": str(input_root),
        "output_root": str(output_root),
        "evidence_root": str(evidence_root),
        "input_rows": total_decisions,
        "output_rows": final_rows,
        "deleted_rows": deleted_rows,
        "output_field_count": len(fields) + 14,
        "years": list(YEARS),
        "summary_file": str(SUMMARY_PATH),
    }
    with open(output_root / "cleaning_manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    validation_text = f"""# 清洗结果验证（v1）

- 输入记录：{total_decisions:,}条。
- 清洗后保留：{final_rows:,}条。
- 删除：{deleted_rows:,}条，均已写入删除证据Parquet并标注原因。
- 记录守恒检查：通过（输入 = 保留 + 删除）。
- 标准化输入只读检查：通过。
- 年度输出：2018—2025年共8个Parquet，每个包含23个正式字段和14个交接字段。
- 工资检查：输出记录至少保留一个大于0的工资端点；两端点都存在时满足最低月薪不高于最高月薪。
- 日期检查：可解析且同时存在的日期满足招聘发布日期不晚于招聘结束日期。

## 交接说明

后续分析优先使用“月薪代表值”。两个工资端点都有效时取均值；只有一个端点有效时直接使用该有效值。
“工资上下限已交换”和“日期顺序已交换”用于识别逻辑修复；“学历要求缺失”和“招聘结束日期缺失”用于缺失机制分析。
原始值保存在同一行的“_原始”字段中；被删除记录在`deleted_records.parquet`中，可按“来源记录ID”追溯。
"""
    VALIDATION_PATH.write_text(validation_text, encoding="utf-8")

    con.close()
    shutil.rmtree(temp_root / "spill_cleaning_v1", ignore_errors=True)
    print(f"CLEANING_SUMMARY={SUMMARY_PATH}")
    print("CLEANING_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
