"""独立复核confirmed_core_v1特征文件。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
YEARS = tuple(range(2018, 2026))
EXPECTED_FIELDS = ["source_record_id", "wage_mid", "ln_wage", "education", "experience", "year_month"]


def main() -> int:
    storage = json.loads(STORAGE_CONFIG_PATH.read_text(encoding="utf-8"))
    cleaned_root = Path(storage["curated_root"]) / "cleaned_v1"
    feature_root = Path(storage["features_root"]) / "confirmed_core_v1"
    con = duckdb.connect()
    total_rows = 0

    for year in YEARS:
        source_path = cleaned_root / f"jobs_{year}_cleaned.parquet"
        feature_path = feature_root / f"jobs_{year}_confirmed_core.parquet"
        if not source_path.is_file() or not feature_path.is_file():
            raise FileNotFoundError(f"{year}年输入或输出文件缺失")
        parquet = pq.ParquetFile(feature_path)
        fields = parquet.schema_arrow.names
        rows = parquet.metadata.num_rows
        parquet.close()
        if fields != EXPECTED_FIELDS:
            raise RuntimeError(f"{year}年字段结构异常：{fields}")

        result = con.execute(
            """
            WITH source AS (
                SELECT "来源记录ID" AS source_record_id,
                       "月薪代表值" AS source_wage,
                       date_trunc('month', "招聘发布日期")::DATE AS source_month
                FROM read_parquet(?)
            ), feature AS (
                SELECT * FROM read_parquet(?)
            )
            SELECT
                count(*) AS source_rows,
                count(feature.source_record_id) AS matched_rows,
                count(*) - count(DISTINCT feature.source_record_id) AS duplicate_feature_ids,
                sum(CASE WHEN feature.source_record_id IS NULL THEN 1 ELSE 0 END) AS missing_feature_rows,
                sum(CASE WHEN abs(feature.wage_mid - source.source_wage) > 1e-12 THEN 1 ELSE 0 END) AS wage_mismatch,
                sum(CASE WHEN abs(feature.ln_wage - ln(feature.wage_mid)) > 1e-12
                              OR feature.ln_wage IS NULL THEN 1 ELSE 0 END) AS log_mismatch,
                sum(CASE WHEN feature.education IS NOT NULL
                              AND feature.education NOT IN ('不限','高中及以下','大专','本科','硕士','博士')
                         THEN 1 ELSE 0 END) AS invalid_education,
                sum(CASE WHEN feature.experience IS NOT NULL
                              AND feature.experience NOT IN ('不限/应届','1年以内','1—3年','3—5年','5年以上')
                         THEN 1 ELSE 0 END) AS invalid_experience,
                sum(CASE WHEN feature.year_month IS NULL OR feature.year_month != source.source_month
                         THEN 1 ELSE 0 END) AS month_mismatch
            FROM source
            LEFT JOIN feature USING (source_record_id)
            """,
            [str(source_path), str(feature_path)],
        ).fetchone()
        names = [item[0] for item in con.description]
        checks = dict(zip(names, result))
        if checks["source_rows"] != rows or checks["matched_rows"] != rows:
            raise RuntimeError(f"{year}年记录匹配失败：{checks}")
        failed = {
            name: value
            for name, value in checks.items()
            if name not in {"source_rows", "matched_rows"} and value != 0
        }
        if failed:
            raise RuntimeError(f"{year}年独立复核失败：{failed}")
        total_rows += rows
        print(f"{year}: VALIDATION_PASS rows={rows:,}", flush=True)

    if total_rows != 5_235_461:
        raise RuntimeError(f"总记录数异常：{total_rows:,}")
    print(f"VALIDATED_ROWS={total_rows}")
    print("CONFIRMED_CORE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
