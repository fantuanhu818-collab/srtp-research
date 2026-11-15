"""导出清洗动作的典型前后对照，供项目组检查和交接。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "qc" / "cleaning_v1_examples.csv"


def main() -> int:
    storage = json.loads((PROJECT_ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
    cleaned_glob = str(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet")
    source_glob = str(Path(storage["curated_root"]) / "schema_23fields_v1" / "jobs_*_23fields.parquet")
    deleted_path = str(Path(storage["evidence_root"]) / "cleaning_v1" / "deleted_records.parquet")
    con = duckdb.connect()

    kept_sql = """
        SELECT
            CASE
              WHEN "工资上下限已交换" THEN '工资上下限颠倒'
              WHEN "日期顺序已交换" THEN '日期顺序颠倒'
              WHEN "工资清洗方式" != '两端点均有效，取均值' THEN '只有一个工资端点有效'
              WHEN "学历要求缺失" THEN '学历要求缺失'
              WHEN "招聘结束日期缺失" THEN '招聘结束日期缺失'
            END AS problem,
            CASE
              WHEN "工资上下限已交换" THEN '交换最低月薪与最高月薪'
              WHEN "日期顺序已交换" THEN '交换发布日期与结束日期'
              WHEN "工资清洗方式" != '两端点均有效，取均值' THEN '保留有效端点，另一端设为缺失'
              ELSE '保留记录并标记缺失'
            END AS action,
            "来源记录ID" AS source_record_id,
            "企业名称" AS company,
            "招聘岗位" AS job_title,
            "工作城市" AS city,
            "最低月薪_原始" AS salary_low_before,
            "最高月薪_原始" AS salary_high_before,
            cast("最低月薪" AS VARCHAR) AS salary_low_after,
            cast("最高月薪" AS VARCHAR) AS salary_high_after,
            cast("月薪代表值" AS VARCHAR) AS salary_representative,
            "招聘发布日期_原始" AS publish_date_before,
            "招聘结束日期_原始" AS end_date_before,
            cast("招聘发布日期" AS VARCHAR) AS publish_date_after,
            cast("招聘结束日期" AS VARCHAR) AS end_date_after,
            "学历要求_原始" AS education_before,
            "学历要求" AS education_after,
            cast("重复组记录数" AS VARCHAR) AS duplicate_group_size,
            NULL::VARCHAR AS kept_source_record_id
        FROM read_parquet(?)
    """
    categories = [
        "工资上下限颠倒",
        "日期顺序颠倒",
        "只有一个工资端点有效",
        "学历要求缺失",
        "招聘结束日期缺失",
    ]
    kept_rows = []
    kept_columns = None
    for category in categories:
        query = f"SELECT * FROM ({kept_sql}) x WHERE problem = ? ORDER BY source_record_id LIMIT 3"
        result = con.execute(query, [cleaned_glob, category])
        kept_columns = [item[0] for item in result.description]
        kept_rows.extend(result.fetchall())

    deleted_sql = """
        WITH source AS (
          SELECT *, filename AS source_file, file_row_number::BIGINT AS source_row_number
          FROM read_parquet(?, filename=true, file_row_number=true)
        ), kept AS (
          SELECT "内容ID" AS content_id, "来源记录ID" AS kept_source_record_id
          FROM read_parquet(?)
        )
        SELECT
          CASE WHEN d.delete_reason = '两个工资端点均无效' THEN '两个工资端点均无效'
               ELSE '重复广告' END AS problem,
          CASE WHEN d.delete_reason = '两个工资端点均无效' THEN '删除记录'
               ELSE '删除重复记录，只保留一条' END AS action,
          d.source_record_id,
          s."企业名称" AS company,
          s."招聘岗位" AS job_title,
          s."工作城市" AS city,
          s."最低月薪" AS salary_low_before,
          s."最高月薪" AS salary_high_before,
          NULL::VARCHAR AS salary_low_after,
          NULL::VARCHAR AS salary_high_after,
          NULL::VARCHAR AS salary_representative,
          s."招聘发布日期" AS publish_date_before,
          s."招聘结束日期" AS end_date_before,
          NULL::VARCHAR AS publish_date_after,
          NULL::VARCHAR AS end_date_after,
          s."学历要求" AS education_before,
          NULL::VARCHAR AS education_after,
          cast(d.duplicate_group_size AS VARCHAR) AS duplicate_group_size,
          k.kept_source_record_id
        FROM read_parquet(?) d
        JOIN source s USING (source_file, source_row_number)
        LEFT JOIN kept k USING (content_id)
        WHERE d.delete_reason = ?
        ORDER BY d.source_record_id
        LIMIT 3
    """
    deleted_rows = []
    for reason in ("两个工资端点均无效", "重复广告，仅保留优先记录"):
        deleted_rows.extend(
            con.execute(deleted_sql, [source_glob, cleaned_glob, deleted_path, reason]).fetchall()
        )

    all_rows = kept_rows + deleted_rows
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(kept_columns)
        writer.writerows(all_rows)
    if len(all_rows) != 21:
        raise RuntimeError(f"应导出21条典型切片，实际为{len(all_rows)}条")
    print(f"EXAMPLE_ROWS={len(all_rows)}")
    print(f"EXAMPLE_OUTPUT={OUTPUT_PATH}")
    print("CLEANING_EXAMPLES_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
