"""构建AI技能特征表（ai_skill_v1）并做交付质量检查。人工标注表由14_make_annotation_sheets.py生成。

接口按《AI技能线数据构建与合并交接_2026-11-16》（数据分析线提供）：
  输入：<curated_root>/cleaned_v1/jobs_{year}_cleaned.parquet（只读）
  输出：<features_root>/ai_skill_v1/jobs_{year}_ai_skill.parquet  每条广告一行，不进Git
        <features_root>/ai_skill_v1/manifest.json                   版本与检查结果
        outputs/qc/ai_skill_v1_summary.csv                          年度汇总（无广告原文，进Git）
        outputs/qc/ai_skill_v1_manifest.json                        同上manifest副本（进Git）

连接键：cleaned_v1.来源记录ID 原值重命名为 source_record_id（字符串），不重新生成、不依赖行序。

运行：
  .venv/bin/python code/python/12_build_ai_skill.py                 # 全部年份（约1小时）
  .venv/bin/python code/python/12_build_ai_skill.py --years 2022
  .venv/bin/python code/python/12_build_ai_skill.py --check-only     # 只做交付检查
成功时依次输出 AI_DELIVERY_GATE=PASS 和 PYTHON_TASK=PASS。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
EXPECTED_TOTAL = 5_235_461
FEATURE_VERSION = "ai_skill_v1"
METHOD = "keyword_rule"
ID, TITLE, DESC = "来源记录ID", "招聘岗位", "职位描述"
SCHEMA = pa.schema([
    ("source_record_id", pa.string()), ("year", pa.int16()),
    ("ai_skill", pa.int8()), ("ai_status", pa.string()),
    ("ai_rule_version", pa.string()), ("ai_method", pa.string()),
    ("ai_hit_terms", pa.string()), ("ai_evidence", pa.string()),
    ("ai_skill_broad", pa.int8()), ("ai_genai", pa.int8()), ("ai_traditional", pa.int8()),
    ("ai_broad_terms", pa.string()), ("ai_intro_only", pa.int8()), ("ai_review_flag", pa.int8()),
])
STATUSES = ["positive", "negative", "text_missing", "uncertain"]

def sql_path(path: Path) -> str:
    """路径放进SQL字符串时转义单引号（如 Belinda's Cottage）。"""
    return path.as_posix().replace("'", "''")


def build_year(matcher: AISkillMatcher, src: Path, dst: Path, year: int) -> dict:
    reader = pq.ParquetFile(src)
    tmp = dst.with_suffix(".parquet.tmp")
    writer = pq.ParquetWriter(tmp, SCHEMA)
    stats = {"year": year, "input_rows": reader.metadata.num_rows, "output_rows": 0,
             **{s: 0 for s in STATUSES}, "ai_skill_broad": 0, "ai_genai": 0,
             "ai_traditional": 0, "ai_intro_only": 0, "ai_review_flag": 0}
    try:
        for batch in reader.iter_batches(batch_size=50_000, columns=[ID, TITLE, DESC]):
            cols = batch.to_pydict()
            rows = {name: [] for name in SCHEMA.names}
            for rid, title, desc in zip(cols[ID], cols[TITLE], cols[DESC]):
                r = matcher.classify(title, desc)
                r.update(source_record_id=None if rid is None else str(rid), year=year,
                         ai_rule_version=matcher.rule_version, ai_method=METHOD)
                for name in SCHEMA.names:
                    rows[name].append(r[name])
                stats[r["ai_status"]] += 1
                for key in ("ai_skill_broad", "ai_genai", "ai_traditional", "ai_intro_only", "ai_review_flag"):
                    stats[key] += r[key] or 0
            stats["output_rows"] += len(rows["source_record_id"])
            writer.write_table(pa.table(rows, schema=SCHEMA))
    finally:
        writer.close()
    tmp.replace(dst)
    judged = stats["positive"] + stats["negative"]
    stats["positive_rate"] = round(stats["positive"] / judged, 6) if judged else None
    stats["missing_rate"] = round((stats["text_missing"] + stats["uncertain"]) / stats["output_rows"], 6)
    stats["broad_rate"] = round(stats["ai_skill_broad"] / judged, 6) if judged else None
    return stats


def validate(out_dir: Path, curated: Path, years: list[int]) -> dict:
    """交接文档第9节的交付检查。任何一项不通过都抛出异常。"""
    ai = sql_path(out_dir / "jobs_*_ai_skill.parquet")
    con = duckdb.connect()
    q = lambda sql: con.execute(sql).fetchone()  # noqa: E731
    checks: dict[str, object] = {}
    present = sorted(int(p.name[5:9]) for p in out_dir.glob("jobs_*_ai_skill.parquet"))
    checks["years_present"] = present

    per_year_ok = True
    for y in present:
        n_in = pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").metadata.num_rows
        n_out = pq.ParquetFile(out_dir / f"jobs_{y}_ai_skill.parquet").metadata.num_rows
        per_year_ok &= n_in == n_out
    checks["rows_equal_input_each_year"] = per_year_ok
    total, distinct, null_ids = q(f"SELECT count(*), count(DISTINCT source_record_id), "
                                  f"count(*) FILTER (WHERE source_record_id IS NULL) FROM read_parquet('{ai}')")
    checks["output_rows"] = total
    checks["unique_ids"] = distinct
    checks["ids_unique"] = total == distinct
    checks["ids_non_null"] = null_ids == 0
    checks["id_type_string"] = str(pq.ParquetFile(out_dir / f"jobs_{present[0]}_ai_skill.parquet")
                                   .schema_arrow.field("source_record_id").type) == "string"
    checks["ai_skill_only_0_1"] = q(f"SELECT count(*) FROM read_parquet('{ai}') "
                                    f"WHERE ai_skill IS NOT NULL AND ai_skill NOT IN (0, 1)")[0] == 0
    checks["status_consistent"] = q(f"""SELECT count(*) FROM read_parquet('{ai}') WHERE NOT (
        (ai_status = 'positive' AND ai_skill = 1) OR (ai_status = 'negative' AND ai_skill = 0)
        OR (ai_status IN ('text_missing', 'uncertain') AND ai_skill IS NULL))""")[0] == 0
    if present == YEARS:
        checks["covers_full_cleaned_v1"] = total == EXPECTED_TOTAL
    # v2删除的63条应在AI表中（AI表覆盖完整cleaned_v1）
    deleted = PROJECT_ROOT / "outputs" / "qc" / "confirmed_core_v2_deleted_rows.csv"
    expected_deleted = q(f"SELECT count(*) FROM read_csv('{sql_path(deleted)}', all_varchar=true) "
                         f"WHERE CAST(year AS INTEGER) IN ({','.join(map(str, present))})")[0]
    found_deleted = q(f"""SELECT count(*) FROM read_csv('{sql_path(deleted)}', all_varchar=true) d
        JOIN read_parquet('{ai}') a USING (source_record_id)""")[0]
    checks["v2_deleted_ids_expected_in_run_years"] = expected_deleted
    checks["v2_deleted_ids_found"] = found_deleted
    checks["v2_deleted_ids_all_present"] = found_deleted == expected_deleted

    failed = [k for k, v in checks.items() if v is False]
    for k, v in checks.items():
        print(f"CHECK {k} = {v}")
    if failed:
        raise RuntimeError(f"交付检查未通过：{failed}")
    print("AI_DELIVERY_GATE=PASS")
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=YEARS)
    ap.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    out_dir = Path(storage["features_root"]) / FEATURE_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    matcher = AISkillMatcher(args.dictionary)
    print(f"RULE_VERSION={matcher.rule_version}")

    if not args.check_only:
        summary = []
        for year in args.years:
            src = curated / f"jobs_{year}_cleaned.parquet"
            if not src.exists():
                raise FileNotFoundError(src)
            t0 = time.time()
            stats = build_year(matcher, src, out_dir / f"jobs_{year}_ai_skill.parquet", year)
            stats["seconds"] = round(time.time() - t0, 1)
            print(stats, flush=True)
            summary.append(stats)
        with (QC_DIR / "ai_skill_v1_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(summary[0]))
            w.writeheader()
            w.writerows(summary)

    checks = validate(out_dir, curated, args.years)
    manifest = {
        "input_data_version": "cleaned_v1",
        "feature_version": FEATURE_VERSION,
        "join_key_source": ID,
        "join_key_output": "source_record_id",
        "ai_rule_version": matcher.rule_version,
        "ai_method": METHOD,
        "dictionary": str(args.dictionary.relative_to(PROJECT_ROOT)) if args.dictionary.is_relative_to(PROJECT_ROOT) else str(args.dictionary),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
        "manual_validation": "未完成：标注样本已生成，待A、B人工标注",
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (out_dir / "manifest.json").write_text(text, encoding="utf-8")
    (QC_DIR / "ai_skill_v1_manifest.json").write_text(text, encoding="utf-8")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
