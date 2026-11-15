"""按已确认规则生成仅含23个正式字段的标准化结构文件。

本步骤只处理字段结构：保留23个正式字段，删除第24个无名列。
不处理重复、工资逻辑、日期逻辑或字段缺失；这些问题只保留给后续清洗。
原始CSV严格只读。
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
RAW_ROOT = Path(os.environ.get("SRTP_RAW_ROOT", r"D:\SRTP\分年份保存数据"))
CONFIG_PATH = PROJECT_ROOT / "config" / "cleaning_rules.json"
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "qc" / "schema_23fields_summary.csv"
YEARS = tuple(range(2018, 2026))
CHUNK_ROWS = 100_000


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def snapshot(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def main() -> int:
    rules = load_json(CONFIG_PATH)
    storage = load_json(STORAGE_CONFIG_PATH)
    official_fields = rules["official_fields"]
    if len(official_fields) != 23 or len(set(official_fields)) != 23:
        raise RuntimeError("cleaning_rules.json中的正式字段必须恰好为23个且不能重复")

    output_root = Path(storage["curated_root"]) / "schema_23fields_v1"
    output_root.mkdir(parents=True, exist_ok=True)
    arrow_schema = pa.schema([pa.field(name, pa.string()) for name in official_fields])
    summary_rows = []
    raw_before = {}

    for year in YEARS:
        input_path = RAW_ROOT / f"上市公司招聘数据{year}.csv"
        output_path = output_root / f"jobs_{year}_23fields.parquet"
        temp_path = output_root / f"jobs_{year}_23fields.parquet.tmp"
        raw_before[str(input_path)] = snapshot(input_path)

        total_rows = 0
        input_columns = None
        dropped_columns = []
        dropped_nonblank = 0
        writer = None
        try:
            for frame in pd.read_csv(
                input_path,
                encoding="utf-8-sig",
                dtype="string",
                keep_default_na=False,
                chunksize=CHUNK_ROWS,
                engine="c",
                on_bad_lines="error",
                low_memory=False,
            ):
                if input_columns is None:
                    input_columns = [str(name) for name in frame.columns]
                    missing = [name for name in official_fields if name not in frame.columns]
                    if missing:
                        raise RuntimeError(f"{year}年缺少正式字段：{missing}")
                    dropped_columns = [name for name in frame.columns if name not in official_fields]
                for name in dropped_columns:
                    values = frame[name].astype("string").fillna("").str.strip()
                    dropped_nonblank += int((values != "").sum())

                selected = frame[official_fields].copy()
                for name in official_fields:
                    selected[name] = selected[name].astype("string")
                table = pa.Table.from_pandas(selected, schema=arrow_schema, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(temp_path, arrow_schema, compression="zstd")
                writer.write_table(table)
                total_rows += len(selected)
                if total_rows % 500_000 < CHUNK_ROWS:
                    print(f"{year}: 已写入 {total_rows:,} 条", flush=True)
        finally:
            if writer is not None:
                writer.close()

        if not temp_path.is_file():
            raise RuntimeError(f"{year}年未生成临时Parquet")
        parquet = pq.ParquetFile(temp_path)
        output_columns = parquet.schema_arrow.names
        output_rows = parquet.metadata.num_rows
        if output_columns != official_fields:
            raise RuntimeError(f"{year}年输出字段不等于正式23字段")
        if output_rows != total_rows:
            raise RuntimeError(f"{year}年输出记录数不一致：{output_rows} != {total_rows}")
        parquet.close()

        os.replace(temp_path, output_path)
        summary_rows.append(
            {
                "year": year,
                "input_rows": total_rows,
                "output_rows": output_rows,
                "input_field_count": len(input_columns or []),
                "output_field_count": len(output_columns),
                "dropped_columns": "; ".join(dropped_columns),
                "dropped_column_nonblank_count": dropped_nonblank,
                "output_path": str(output_path),
                "output_size_bytes": output_path.stat().st_size,
                "schema_version": rules["schema_version"],
            }
        )
        print(
            f"{year}: SCHEMA_PASS rows={output_rows:,} fields={len(output_columns)} "
            f"dropped={dropped_columns}",
            flush=True,
        )

    for raw_path, old_snapshot in raw_before.items():
        if snapshot(Path(raw_path)) != old_snapshot:
            raise RuntimeError(f"原始文件在运行期间发生变化：{raw_path}")

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    manifest = {
        "schema_version": rules["schema_version"],
        "official_field_count": 23,
        "official_fields": official_fields,
        "years": list(YEARS),
        "summary_file": str(SUMMARY_PATH),
        "scope": "仅统一字段结构；未处理重复、逻辑异常和字段缺失。",
    }
    with open(output_root / "schema_manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    print(f"SCHEMA_SUMMARY={SUMMARY_PATH}")
    print("SCHEMA_STANDARDIZATION_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
