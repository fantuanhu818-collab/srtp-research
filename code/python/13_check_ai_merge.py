"""合并测试：confirmed_core_v2 左连接 ai_skill_v1（按 source_record_id）。

对应《AI技能线数据构建与合并交接_2026-11-16》第8—9节。只读两张表，不生成合并数据。
  .venv/bin/python code/python/13_check_ai_merge.py
  .venv/bin/python code/python/13_check_ai_merge.py --v2-dir <confirmed_core_v2目录>
成功时输出 AI_MERGE_GATE=PASS；结果写入 outputs/qc/ai_skill_v1_merge_check.csv。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--v2-dir", type=Path)
    args = ap.parse_args()
    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    v2_dir = args.v2_dir or Path(storage["features_root"]) / "confirmed_core_v2"
    v2 = sql_path(v2_dir / "*.parquet")
    ai = sql_path(Path(storage["features_root"]) / "ai_skill_v1" / "jobs_*_ai_skill.parquet")
    deleted = sql_path(PROJECT_ROOT / "outputs" / "qc" / "confirmed_core_v2_deleted_rows.csv")  # 63条v2删除证据

    con = duckdb.connect()
    con.execute(f"CREATE VIEW v2 AS SELECT CAST(source_record_id AS VARCHAR) AS id FROM read_parquet('{v2}')")
    con.execute(f"CREATE VIEW ai AS SELECT source_record_id AS id, ai_skill, ai_status FROM read_parquet('{ai}')")
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    r = {
        "v2左表记录数": one("SELECT count(*) FROM v2"),
        "v2唯一ID数": one("SELECT count(DISTINCT id) FROM v2"),
        "AI特征记录数": one("SELECT count(*) FROM ai"),
        "v2成功匹配AI特征": one("SELECT count(*) FROM v2 JOIN ai USING (id)"),
        "v2未匹配AI特征（merge_missing）": one("SELECT count(*) FROM v2 ANTI JOIN ai USING (id)"),
        "AI表多出的记录": one("SELECT count(*) FROM ai ANTI JOIN v2 USING (id)"),
        "合并后总记录数": one("SELECT count(*) FROM v2 LEFT JOIN ai USING (id)"),
        "已匹配但ai_skill缺失（测量缺失）": one("SELECT count(*) FROM v2 JOIN ai USING (id) WHERE ai_skill IS NULL"),
        "合并后ai_skill=1": one("SELECT count(*) FROM v2 JOIN ai USING (id) WHERE ai_skill = 1"),
        "合并后ai_skill=0": one("SELECT count(*) FROM v2 JOIN ai USING (id) WHERE ai_skill = 0"),
    }
    extra_not_in_deleted = one(f"""SELECT count(*) FROM (SELECT id FROM ai ANTI JOIN v2 USING (id)) x
        WHERE id NOT IN (SELECT source_record_id FROM read_csv('{deleted}', all_varchar=true))""")
    r["AI表多出记录中不属于v2删除清单的"] = extra_not_in_deleted

    for k, v in r.items():
        print(f"{k}: {v:,}")
    out = PROJECT_ROOT / "outputs" / "qc" / "ai_skill_v1_merge_check.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([["检查项", "结果"], *r.items()])

    ok = (r["v2左表记录数"] == r["v2唯一ID数"] and r["v2未匹配AI特征（merge_missing）"] == 0
          and r["合并后总记录数"] == r["v2左表记录数"] and extra_not_in_deleted == 0)
    if not ok:
        raise SystemExit("AI_MERGE_GATE=FAIL")
    print("AI_MERGE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
