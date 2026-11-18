"""规则v0.2：核对第4步新词在全样本上的实际命中（方案第4步之后、第5步重建之前）。

第17步按jieba分词统计候选词出现次数；词典按正则子串匹配。短中文词可能嵌在别的词里被多匹配
（如“可灵”匹配“可灵活”）。本脚本对每个新词（id以w_开头）统计：
  n_regex       要求句里正则命中的广告数
  n_regex_alone 其中不含v0.1.1严格词的广告数（与17的“单独出现广告数”同口径）
并和17的分词计数对比；比值过高的词要人工看例句。

输出（无原文，进Git）：outputs/qc/ai_new_terms_check_v0.2.csv
输出（含原句，不进Git）：<features_root>/ai_skill_v0.2_work/new_terms/examples.csv

运行：.venv/bin/python code/python/23_check_new_terms.py
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import pickle
import re
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_w2v_text as T  # noqa: E402
from ai_skill_matcher import AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DICT = PROJECT_ROOT / "config" / "ai_skill_dictionary_v0.2_draft.json"
DICT_V01 = PROJECT_ROOT / "config" / "ai_skill_dictionary_v0.1.json"
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
ID, TITLE, DESC = "来源记录ID", "招聘岗位", "职位描述"
N_EXAMPLES = 10
CTX = 15

_m: AISkillMatcher | None = None
_new: list = []
_old_strict: list = []
_pre: re.Pattern | None = None


def _init(path: str) -> None:
    global _m, _new, _old_strict, _pre
    _m = AISkillMatcher(path)
    _new = [t for t in _m.terms if t.id.startswith("w_")]
    _old_strict = [t for t in AISkillMatcher(DICT_V01).terms if t.tier == "strict"]
    _pre = re.compile("|".join(t.regex.pattern for t in _new), re.IGNORECASE)


def _batch(rows: list[tuple]) -> tuple[Counter, dict]:
    n, ex = Counter(), {}
    for rid, title, desc in rows:
        if not _pre.search(f"{title or ''}\n{desc or ''}"):
            continue
        clauses = T.requirement_clauses(_m, title, desc)
        hits = {}
        for clause in clauses:
            for t in _new:
                if t.id not in hits:
                    m = t.regex.search(clause)
                    if m:
                        hits[t.id] = clause[max(0, m.start() - CTX):m.end() + CTX]
        if not hits:
            continue
        alone = not any(t.regex.search(c) for c in clauses for t in _old_strict)
        for tid, ctx in hits.items():
            n[(tid, "all")] += 1
            if alone:
                n[(tid, "alone")] += 1
                heap = ex.setdefault(tid, [])
                item = (hash((rid, tid)) & 0xFFFFFFFF, ctx)
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
    out_dir = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "new_terms"
    out_dir.mkdir(parents=True, exist_ok=True)

    def tasks():
        for y in YEARS:
            for b in pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").iter_batches(
                    batch_size=20_000, columns=[ID, TITLE, DESC]):
                d = b.to_pydict()
                yield list(zip(d[ID], d[TITLE], d[DESC]))

    t0, n, ex = time.time(), Counter(), {}
    with Pool(args.workers, initializer=_init, initargs=(str(DICT),)) as pool:
        for bn, bex in pool.imap_unordered(_batch, tasks(), chunksize=1):
            n.update(bn)
            for tid, items in bex.items():
                heap = ex.setdefault(tid, [])
                for item in items:
                    if len(heap) < N_EXAMPLES:
                        heapq.heappush(heap, item)
                    elif item > heap[0]:
                        heapq.heapreplace(heap, item)
    print(f"DONE elapsed={time.time() - t0:.0f}s", flush=True)
    with (out_dir / "raw_counts.pkl").open("wb") as f:
        pickle.dump((n, ex), f)

    spec = json.loads(DICT.read_text(encoding="utf-8"))
    cands = {}
    with (QC_DIR / "ai_w2v_candidates_v0.2.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cands[r["candidate"]] = r
    tok = {}
    for cand, r in cands.items():  # 与20_build_dictionary_v0.2.new_term的id规则一致
        tid = ("w_" + re.sub(r"[^0-9a-zA-Z]+", "_", cand).strip("_").lower()
               if re.fullmatch(r"[\x00-\x7f]+", cand) else "w_" + cand)
        tok[tid] = (cand, int(r["n_all"]), int(r["n_alone"] or 0))
    rows = []
    for t in spec["terms"]:
        if not t["id"].startswith("w_"):
            continue
        cand, n_tok, n_tok_alone = tok[t["id"]]
        a, al = n[(t["id"], "all")], n[(t["id"], "alone")]
        rows.append({"id": t["id"], "candidate": cand, "tier": t["tier"], "pattern": t["pattern"],
                     "n_token": n_tok, "n_regex": a, "ratio": round(a / n_tok, 2) if n_tok else None,
                     "n_token_alone": n_tok_alone, "n_regex_alone": al,
                     "extra_alone": al - n_tok_alone})
    rows.sort(key=lambda r: -r["extra_alone"])
    with (QC_DIR / "ai_new_terms_check_v0.2.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (out_dir / "examples.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "tier", "n_token_alone", "n_regex_alone", "context_alone"])
        for r in rows:
            for _, ctx in sorted(ex.get(r["id"], []), reverse=True):
                w.writerow([r["id"], r["tier"], r["n_token_alone"], r["n_regex_alone"], ctx.replace("\n", " ")])
    print("total regex alone:", sum(r["n_regex_alone"] for r in rows), "token alone:", sum(r["n_token_alone"] for r in rows))
    for r in rows[:30]:
        print(r["id"], r["tier"], r["n_token_alone"], "→", r["n_regex_alone"])
    print(f"EXAMPLES → {out_dir / 'examples.csv'}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
