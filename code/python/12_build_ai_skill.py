"""生成AI技能变量，并抽取人工标注样本。

输入：<curated_root>/cleaned_v1/jobs_{year}_cleaned.parquet（只读）
输出：
  <features_root>/ai_skill_v0.1/ai_skill_{year}.parquet   每条广告一行（含命中证据，不进Git）
  outputs/qc/ai_skill_v0.1_summary.csv                    年度汇总（不含广告原文，可进Git）
  <analysis_root>/ai_annotation_v0.1/annotation_sample.csv 人工标注样本（含原文，不进Git）

运行：
  .venv/bin/python code/python/12_build_ai_skill.py                 # 全部年份
  .venv/bin/python code/python/12_build_ai_skill.py --years 2022 --limit 50000
  .venv/bin/python code/python/12_build_ai_skill.py --sample-only    # 只重新抽样
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
YEARS = list(range(2018, 2026))
ID, TITLE, DESC = "来源记录ID", "招聘岗位", "职位描述"
OUT_DIR_NAME = "ai_skill_v0.1"
SCHEMA = pa.schema([
    ("source_record_id", pa.string()), ("year", pa.int16()),
    ("ai_skill", pa.int8()), ("ai_skill_broad", pa.int8()),
    ("ai_genai", pa.int8()), ("ai_traditional", pa.int8()),
    ("ai_strict_terms", pa.string()), ("ai_broad_terms", pa.string()),
    ("ai_intro_only", pa.int8()), ("ai_review_flag", pa.int8()),
    ("ai_evidence", pa.string()), ("ai_rule_version", pa.string()),
])
# 分层抽样：(层名, SQL条件, 默认样本量)。命中层多抽，用于估计查准率；未命中层用于估计漏判。
STRATA = [
    ("strict_hit", "ai_skill = 1", 100),
    ("broad_only", "ai_skill = 0 AND ai_skill_broad = 1", 60),
    ("intro_only", "ai_intro_only = 1", 40),
    ("review_only", "ai_review_flag = 1 AND ai_skill_broad = 0", 30),
    ("no_hit", "ai_skill_broad = 0 AND ai_intro_only = 0 AND ai_review_flag = 0", 70),
]


def build_year(matcher: AISkillMatcher, src: Path, dst: Path, year: int, limit: int | None) -> dict:
    reader = pq.ParquetFile(src)
    tmp = dst.with_suffix(".parquet.tmp")
    writer = pq.ParquetWriter(tmp, SCHEMA)
    stats = dict(year=year, n=0, text_missing=0, ai_skill=0, ai_skill_broad=0, ai_genai=0,
                 ai_traditional=0, ai_intro_only=0, ai_review_flag=0)
    try:
        for batch in reader.iter_batches(batch_size=50_000, columns=[ID, TITLE, DESC]):
            cols = batch.to_pydict()
            rows = {name: [] for name in SCHEMA.names}
            for rid, title, desc in zip(cols[ID], cols[TITLE], cols[DESC]):
                if limit is not None and stats["n"] >= limit:
                    break
                r = matcher.classify(title, desc)
                r.update(source_record_id=rid, year=year, ai_rule_version=matcher.rule_version)
                for name in SCHEMA.names:
                    rows[name].append(r[name])
                stats["n"] += 1
                if r["ai_skill"] is None:
                    stats["text_missing"] += 1
                for key in ("ai_skill", "ai_skill_broad", "ai_genai", "ai_traditional", "ai_intro_only", "ai_review_flag"):
                    stats[key] += r[key] or 0
            if rows["source_record_id"]:
                writer.write_table(pa.table(rows, schema=SCHEMA))
            if limit is not None and stats["n"] >= limit:
                break
    finally:
        writer.close()
    tmp.replace(dst)
    valid = stats["n"] - stats["text_missing"]
    for key in ("ai_skill", "ai_skill_broad", "ai_genai", "ai_traditional"):
        stats[f"{key}_rate"] = round(stats[key] / valid, 6) if valid else None
    return stats


def check_unique_ids(out_dir: Path) -> None:
    glob = (out_dir / "ai_skill_*.parquet").as_posix()
    n, unique = duckdb.sql(f"SELECT count(*), count(DISTINCT source_record_id) FROM read_parquet('{glob}')").fetchone()
    if n != unique:
        raise RuntimeError(f"来源记录ID不唯一：{n}行，{unique}个不同ID")
    print(f"ID_CHECK=PASS rows={n}")


def make_sample(out_dir: Path, curated: Path, sample_dir: Path, seed: int) -> Path:
    sample_dir.mkdir(parents=True, exist_ok=True)
    glob_ai = (out_dir / "ai_skill_*.parquet").as_posix()
    glob_text = (curated / "jobs_*_cleaned.parquet").as_posix()
    con = duckdb.connect()
    con.execute(f"SELECT setseed({(seed % 1000) / 1000})")
    parts = []
    for name, cond, size in STRATA:
        parts.append(f"""(SELECT '{name}' AS stratum, * FROM read_parquet('{glob_ai}')
                         WHERE {cond} ORDER BY random() LIMIT {size})""")
    query = f"""
        WITH s AS ({' UNION ALL '.join(parts)})
        SELECT row_number() OVER (ORDER BY random()) AS annotation_no,
               s.stratum, s.source_record_id, s.year, t."{TITLE}" AS job_title, t."{DESC}" AS job_description,
               s.ai_skill, s.ai_skill_broad, s.ai_strict_terms, s.ai_broad_terms, s.ai_evidence,
               NULL AS label_ai_skill, NULL AS label_ai_type, NULL AS label_error_type,
               NULL AS annotator, NULL AS note
        FROM s JOIN read_parquet('{glob_text}') t ON t."{ID}" = s.source_record_id
        ORDER BY annotation_no"""
    path = sample_dir / "annotation_sample.csv"
    con.execute(f"COPY ({query}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())  # BOM：Excel/WPS打开中文不乱码
    counts = con.execute(f"SELECT stratum, count(*) FROM read_csv_auto('{path.as_posix()}') GROUP BY 1 ORDER BY 1").fetchall()
    print("SAMPLE", dict(counts), "->", path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=YEARS)
    ap.add_argument("--limit", type=int, help="每年只处理前N条（试跑用）")
    ap.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--sample-only", action="store_true")
    ap.add_argument("--seed", type=int, default=20261116)
    args = ap.parse_args()

    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    out_dir = Path(storage["features_root"]) / OUT_DIR_NAME
    sample_dir = Path(storage["analysis_root"]) / "ai_annotation_v0.1"
    out_dir.mkdir(parents=True, exist_ok=True)
    matcher = AISkillMatcher(args.dictionary)
    print(f"RULE_VERSION={matcher.rule_version}")

    if not args.sample_only:
        summary = []
        for year in args.years:
            src = curated / f"jobs_{year}_cleaned.parquet"
            if not src.exists():
                raise FileNotFoundError(src)
            t0 = time.time()
            stats = build_year(matcher, src, out_dir / f"ai_skill_{year}.parquet", year, args.limit)
            stats["seconds"] = round(time.time() - t0, 1)
            print(stats)
            summary.append(stats)
        summary_path = PROJECT_ROOT / "outputs" / "qc" / "ai_skill_v0.1_summary.csv"
        with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(summary[0]))
            w.writeheader()
            w.writerows(summary)
        print("SUMMARY ->", summary_path)
        check_unique_ids(out_dir)

    make_sample(out_dir, curated, sample_dir, args.seed)
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
