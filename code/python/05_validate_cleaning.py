"""独立复核cleaned_v1，不复用清洗程序中的决策表。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG = PROJECT_ROOT / "config" / "storage_paths.json"


def main() -> int:
    storage = json.loads(STORAGE_CONFIG.read_text(encoding="utf-8"))
    cleaned_root = Path(storage["curated_root"]) / "cleaned_v1"
    files = sorted(cleaned_root.glob("jobs_*_cleaned.parquet"))
    if len(files) != 8:
        raise RuntimeError(f"应有8个年度文件，实际为{len(files)}个")

    field_counts = {len(pq.ParquetFile(path).schema_arrow.names) for path in files}
    if field_counts != {37}:
        raise RuntimeError(f"输出字段数异常：{field_counts}")

    con = duckdb.connect()
    result = con.execute(
        """
        SELECT
            count(*) AS record_count,
            count(*) - count(DISTINCT "内容ID") AS duplicate_content_id_count,
            sum(CASE WHEN coalesce("最低月薪", 0) <= 0
                          AND coalesce("最高月薪", 0) <= 0 THEN 1 ELSE 0 END) AS both_salary_invalid_count,
            sum(CASE WHEN "最低月薪" IS NOT NULL AND "最高月薪" IS NOT NULL
                          AND "最低月薪" > "最高月薪" THEN 1 ELSE 0 END) AS salary_reversed_count,
            sum(CASE WHEN "招聘发布日期" IS NOT NULL AND "招聘结束日期" IS NOT NULL
                          AND "招聘结束日期" < "招聘发布日期" THEN 1 ELSE 0 END) AS date_reversed_count,
            sum(CASE WHEN "招聘结束日期缺失" != ("招聘结束日期" IS NULL)
                     THEN 1 ELSE 0 END) AS end_date_flag_mismatch_count,
            sum(CASE WHEN "学历要求缺失" != ("学历要求" IS NULL)
                     THEN 1 ELSE 0 END) AS education_flag_mismatch_count,
            sum(CASE WHEN "月薪代表值" IS NULL OR "月薪代表值" <= 0
                     THEN 1 ELSE 0 END) AS representative_salary_invalid_count
        FROM read_parquet(?)
        """,
        [str(cleaned_root / "jobs_*_cleaned.parquet")],
    ).fetchone()
    names = [column[0] for column in con.description]
    checks = dict(zip(names, result))
    expected_rows = 5_235_461
    if checks["record_count"] != expected_rows:
        raise RuntimeError(f"清洗记录数异常：{checks['record_count']:,} != {expected_rows:,}")
    failed = {name: value for name, value in checks.items() if name != "record_count" and value != 0}
    if failed:
        raise RuntimeError(f"独立复核失败：{failed}")

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print("INDEPENDENT_CLEANING_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
