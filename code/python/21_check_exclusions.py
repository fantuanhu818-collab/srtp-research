"""规则v0.2第5步：在全样本上核对新增排除规则（方案第6.1节第6条）。

对v0.2草稿词典中每条新增排除规则，统计：词条在要求句（岗位名称+非公司介绍句）里出现、但被这条规则排除的广告数，
按ChatGPT前后分开；并随机抽20条被排除的句子，供人工查看有没有误伤真正的AI广告。

输出（无原文，进Git）：outputs/qc/ai_exclusion_check_v0.2.csv
输出（含原句，不进Git）：<features_root>/ai_skill_v0.2_work/exclusions/examples.csv

运行：.venv/bin/python code/python/21_check_exclusions.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_w2v_text as T  # noqa: E402
from ai_skill_matcher import AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DICT = PROJECT_ROOT / "config" / "ai_skill_dictionary_v0.2_draft.json"
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
ID, TITLE, DESC, PUB = "来源记录ID", "招聘岗位", "职位描述", "招聘发布日期"
RELEASE = date(2022, 11, 30)
N_EXAMPLES = 20

_m: AISkillMatcher | None = None
_rules: list[tuple[int, list, re.Pattern]] = []
_pre: re.Pattern | None = None


def load_rules(path: Path) -> list[dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return [e for e in spec["term_exclusions"] if e["note"].startswith("v0.2")]


def _init(path: str) -> None:
    global _m, _rules, _pre
    _m = AISkillMatcher(path)
    by_id = {t.id: t for t in _m.terms}
    _rules = [(i, [by_id[t] for t in e["terms"]], re.compile(e["clause_pattern"], re.IGNORECASE))
              for i, e in enumerate(load_rules(Path(path)))]
    _pre = re.compile("|".join(t.regex.pattern for _, ts, _ in _rules for t in ts), re.IGNORECASE)


def _key(rid: str, i: int) -> int:
    return int.from_bytes(hashlib.blake2b(f"{T.SEED}|{rid}|{i}".encode(), digest_size=8).digest(), "big")


def _batch(rows: list[tuple]) -> tuple[Counter, dict]:
    n, ex = Counter(), {}
    for rid, title, desc, pub in rows:
        text = f"{title or ''}\n{desc or ''}"
        if not _pre.search(text):
            continue
        period = "na" if pub is None else ("post" if pub >= RELEASE else "pre")
        hit_rules = {}
        for clause in T.requirement_clauses(_m, title, desc):
            for i, terms, pat in _rules:
                if i not in hit_rules and any(t.regex.search(clause) for t in terms) and pat.search(clause):
                    hit_rules[i] = clause
        for i, clause in hit_rules.items():
            n[(i, period)] += 1
            heap = ex.setdefault(i, [])
            item = (-_key(rid, i), rid, period, clause[:200])
            if len(heap) < N_EXAMPLES:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    return n, ex


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    out_dir = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "exclusions"
    out_dir.mkdir(parents=True, exist_ok=True)
    rules = load_rules(DICT)

    def tasks():
        for y in YEARS:
            for b in pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").iter_batches(
                    batch_size=20_000, columns=[ID, TITLE, DESC, PUB]):
                d = b.to_pydict()
                yield list(zip(d[ID], d[TITLE], d[DESC], d[PUB]))

    t0, n, ex = time.time(), Counter(), {}
    with Pool(args.workers, initializer=_init, initargs=(str(DICT),)) as pool:
        for bn, bex in pool.imap_unordered(_batch, tasks(), chunksize=1):
            n.update(bn)
            for i, items in bex.items():
                heap = ex.setdefault(i, [])
                for item in items:
                    if len(heap) < N_EXAMPLES:
                        heapq.heappush(heap, item)
                    elif item > heap[0]:
                        heapq.heapreplace(heap, item)
    print(f"DONE elapsed={time.time() - t0:.0f}s", flush=True)

    rows = [{"rule": i + 1, "terms": "|".join(e["terms"]), "note": e["note"], "clause_pattern": e["clause_pattern"],
             "excluded_ads_pre": n[(i, "pre")], "excluded_ads_post": n[(i, "post")], "excluded_ads_date_missing": n[(i, "na")],
             "excluded_ads_all": n[(i, "pre")] + n[(i, "post")] + n[(i, "na")]} for i, e in enumerate(rules)]
    with (QC_DIR / "ai_exclusion_check_v0.2.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (out_dir / "examples.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule", "note", "source_record_id", "period", "clause", "误伤？(1是/0否)"])
        for i, e in enumerate(rules):
            for _, rid, period, clause in sorted(ex.get(i, []), reverse=True):
                w.writerow([i + 1, e["note"][:30], rid, period, clause, ""])
    for r in rows:
        print(r["rule"], r["terms"], r["excluded_ads_pre"], r["excluded_ads_post"])
    print(f"EXAMPLES → {out_dir / 'examples.csv'}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
