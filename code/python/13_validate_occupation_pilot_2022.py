"""独立复核2022年 occupation_id 试运行输出的结构和连接关系。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
EXPECTED_ROWS = 328_548
EXPECTED_FIELDS = [
    "source_record_id", "occupation_l1", "occupation_l1_name", "occupation_id",
    "occupation_name", "job_title_raw", "job_title_normalized", "occupation_rule_id",
    "occupation_match_text", "occupation_source", "occupation_confidence",
    "occupation_status", "occupation_match_count", "occupation_secondary_hits",
]


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    core_path = Path(storage["features_root"]) / "confirmed_core_v2" / "jobs_2022_confirmed_core.parquet"
    pilot_path = Path(storage["features_root"]) / "occupation_pilot_v0.1" / "jobs_2022_occupation_pilot.parquet"
    parquet = pq.ParquetFile(pilot_path)
    fields = parquet.schema_arrow.names
    rows = parquet.metadata.num_rows
    parquet.close()
    if fields != EXPECTED_FIELDS or rows != EXPECTED_ROWS:
        raise RuntimeError(f"试运行输出字段或行数异常：rows={rows}, fields={fields}")

    allowed_ids = sorted(rules["occupation_names"])
    placeholders = ",".join("?" for _ in allowed_ids)
    con = duckdb.connect()
    query = f"""
        WITH core AS (SELECT source_record_id FROM read_parquet(?)),
        pilot AS (SELECT * FROM read_parquet(?))
        SELECT
          (SELECT count(*) FROM core) AS core_rows,
          count(*) AS pilot_rows,
          count(*) - count(DISTINCT pilot.source_record_id) AS duplicate_ids,
          sum((core.source_record_id IS NULL)::INTEGER) AS ids_not_in_core,
          sum((pilot.occupation_id NOT IN ({placeholders}))::INTEGER) AS invalid_occupation,
          sum((pilot.occupation_l1 != substr(pilot.occupation_id, 1, 1))::INTEGER) AS invalid_l1,
          sum((pilot.occupation_id = 'Z99' AND pilot.occupation_confidence != 'unclassified')::INTEGER)
              AS invalid_z99_confidence,
          sum((pilot.occupation_id != 'Z99' AND pilot.occupation_rule_id = '')::INTEGER)
              AS classified_without_rule,
          sum((pilot.job_title_raw IS NULL OR pilot.job_title_normalized IS NULL)::INTEGER)
              AS missing_titles
        FROM pilot LEFT JOIN core USING (source_record_id)
    """
    values = con.execute(query, [str(core_path), str(pilot_path), *allowed_ids]).fetchone()
    names = [item[0] for item in con.description]
    checks = dict(zip(names, values))
    failed = {
        name: value for name, value in checks.items()
        if name not in {"core_rows", "pilot_rows"} and value != 0
    }
    if checks["core_rows"] != EXPECTED_ROWS or checks["pilot_rows"] != EXPECTED_ROWS or failed:
        raise RuntimeError(f"职业试运行独立复核失败：{checks}")
    print(f"VALIDATED_ROWS={rows}")
    print("OCCUPATION_PILOT_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
