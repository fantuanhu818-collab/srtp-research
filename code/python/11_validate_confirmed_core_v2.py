"""独立复核 confirmed_core_v2 的行数、连接关系和核心变量约束。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
DELETED_PATH = PROJECT_ROOT / "outputs" / "qc" / "confirmed_core_v2_deleted_rows.csv"
YEARS = tuple(range(2018, 2026))
EXPECTED_FIELDS = [
    "source_record_id", "wage_mid", "ln_wage", "education", "experience",
    "firm_id", "city_id", "year_month",
]
EXPECTED_OUTPUT_ROWS = 5_235_398


def main() -> int:
    storage = json.loads(STORAGE_CONFIG_PATH.read_text(encoding="utf-8"))
    source_root = Path(storage["curated_root"]) / "cleaned_v1"
    feature_root = Path(storage["features_root"]) / "confirmed_core_v2"
    con = duckdb.connect()
    total_rows = 0
    total_deleted = 0

    for year in YEARS:
        source_path = source_root / f"jobs_{year}_cleaned.parquet"
        feature_path = feature_root / f"jobs_{year}_confirmed_core.parquet"
        parquet = pq.ParquetFile(feature_path)
        rows = parquet.metadata.num_rows
        fields = parquet.schema_arrow.names
        parquet.close()
        if fields != EXPECTED_FIELDS:
            raise RuntimeError(f"{year}年字段结构异常：{fields}")

        query = r"""
        WITH source0 AS (
            SELECT *, regexp_replace(trim(cast("学历要求" AS VARCHAR)), '\s+', '', 'g') AS edu_norm
            FROM read_parquet(?)
        ), source AS (
            SELECT "来源记录ID" AS source_record_id,
                   "月薪代表值" AS source_wage,
                   date_trunc('month', "招聘发布日期")::DATE AS source_month,
                   "关联股票代码" AS source_firm,
                   edu_norm
            FROM source0
            WHERE edu_norm IS NULL
               OR edu_norm NOT IN ('以上', '0', '-山东-青岛-城阳区-')
        ), feature AS (
            SELECT * FROM read_parquet(?)
        )
        SELECT
            (SELECT count(*) FROM source0) - (SELECT count(*) FROM source) AS deleted_rows,
            count(*) AS source_rows,
            count(feature.source_record_id) AS matched_rows,
            count(*) - count(DISTINCT feature.source_record_id) AS duplicate_feature_ids,
            sum(CASE WHEN feature.source_record_id IS NULL THEN 1 ELSE 0 END) AS missing_feature_rows,
            sum(CASE WHEN abs(feature.wage_mid - source.source_wage) > 1e-12 THEN 1 ELSE 0 END) AS wage_mismatch,
            sum(CASE WHEN feature.ln_wage IS NULL
                          OR abs(feature.ln_wage - ln(feature.wage_mid)) > 1e-12
                     THEN 1 ELSE 0 END) AS log_mismatch,
            sum(CASE WHEN feature.education IS NOT NULL
                          AND feature.education NOT IN ('不限','高中及以下','大专','本科','硕士','博士')
                     THEN 1 ELSE 0 END) AS invalid_education,
            sum(CASE WHEN source.edu_norm IN ('其他','其它') AND feature.education != '不限'
                     THEN 1 ELSE 0 END) AS other_education_not_unlimited,
            sum(CASE WHEN feature.experience IS NOT NULL
                          AND feature.experience NOT IN ('不限/应届','1年以内','1—3年','3—5年','5年以上')
                     THEN 1 ELSE 0 END) AS invalid_experience,
            sum(CASE WHEN feature.firm_id IS NOT NULL
                          AND NOT regexp_full_match(feature.firm_id, '[0-9]{6}')
                     THEN 1 ELSE 0 END) AS invalid_firm_format,
            sum(CASE WHEN source.source_firm IS NOT NULL AND feature.firm_id !=
                          lpad(cast(cast(source.source_firm AS DOUBLE)::BIGINT AS VARCHAR), 6, '0')
                     THEN 1 ELSE 0 END) AS firm_mismatch,
            sum(CASE WHEN feature.city_id IS NOT NULL AND
                          (regexp_matches(feature.city_id, '[、,，;；|]')
                           OR ((regexp_matches(feature.city_id, '区$')
                                AND NOT regexp_matches(feature.city_id, '地区$'))
                               OR regexp_matches(feature.city_id, '(县|旗|开发区|产业园)$'))
                              AND feature.city_id NOT IN ('雄安新区','西咸新区','神农架林区'))
                     THEN 1 ELSE 0 END) AS invalid_city_format,
            sum(CASE WHEN feature.year_month IS NULL OR feature.year_month != source.source_month
                     THEN 1 ELSE 0 END) AS month_mismatch
        FROM source
        LEFT JOIN feature USING (source_record_id)
        """
        result = con.execute(query, [str(source_path), str(feature_path)]).fetchone()
        names = [item[0] for item in con.description]
        checks = dict(zip(names, result))
        if checks["source_rows"] != rows or checks["matched_rows"] != rows:
            raise RuntimeError(f"{year}年记录匹配失败：{checks}")
        failed = {
            name: value for name, value in checks.items()
            if name not in {"deleted_rows", "source_rows", "matched_rows"} and value != 0
        }
        if failed:
            raise RuntimeError(f"{year}年独立复核失败：{failed}")
        total_rows += rows
        total_deleted += checks["deleted_rows"]
        print(f"{year}: VALIDATION_PASS output={rows:,} deleted={checks['deleted_rows']:,}", flush=True)

    with open(DELETED_PATH, "r", encoding="utf-8-sig", newline="") as handle:
        evidence = list(csv.DictReader(handle))
    evidence_ids = {row["source_record_id"] for row in evidence}
    if len(evidence) != 63 or len(evidence_ids) != 63:
        raise RuntimeError("删除证据必须恰好包含63条不同来源记录")
    if total_deleted != 63 or total_rows != EXPECTED_OUTPUT_ROWS:
        raise RuntimeError(f"总量异常：deleted={total_deleted:,}, output={total_rows:,}")

    print(f"VALIDATED_ROWS={total_rows}")
    print(f"VALIDATED_DELETED_ROWS={total_deleted}")
    print("CONFIRMED_CORE_V2_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
