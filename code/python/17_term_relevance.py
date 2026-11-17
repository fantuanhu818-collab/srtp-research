"""规则v0.2第3步：按共现给所有词打相关度分，并生成A、B的候选词筛词表。

方案：docs/AI技能识别调整方案与对接_2026-11-16.md 第3.4—3.5节、第4节。
  单位：一条广告的要求句（岗位名称 + 非公司介绍句），全样本 cleaned_v1。
  核心词：传统AI = 机器学习、计算机视觉、自然语言处理（全部年份）；
          生成式AI = 大语言模型（含限定写法）、LLM（只用2022-11-30及以后的广告）。
  相关度 = 同时出现该词和某个核心词（不算它自己）的广告数 ÷ 出现该词的广告数。
  门槛（预先写定）：≥30% 严格词；10%—30% 条件词；<10% 宽泛词；出现不足30条 → 条件词。
  现有词用 ai_skill_matcher 的正则（含排除规则）匹配；候选词按 jieba 分词后的整词匹配（与训练语料一致）。
  候选词：出现广告数≥30；超过400个时按最高相似度取前400个。

输入（只读）：cleaned_v1；<features_root>/ai_skill_v0.2_work/w2v/{candidates_raw.csv, phrases.pkl}
输出（不进Git，含广告原句）：
  <features_root>/ai_skill_v0.2_work/relevance/candidates_full.csv     候选词全部信息（含建议层级、例句）
  <analysis_root>/ai_w2v_screening_v0.2/筛词表_A.csv、筛词表_B.csv     交给A、B独立填写
输出（进Git，无原文）：outputs/qc/ai_term_relevance_v0.2.csv（现有词）、outputs/qc/ai_w2v_candidates_v0.2.csv、
  outputs/qc/ai_term_relevance_v0.2_summary.json

运行：.venv/bin/python code/python/17_term_relevance.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import sys
import time
from collections import Counter
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_w2v_text as T  # noqa: E402
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
ID, TITLE, DESC, PUB = "来源记录ID", "招聘岗位", "职位描述", "招聘发布日期"
RELEASE = date.fromisoformat(T.CHATGPT_RELEASE)
TRAD_CORE = {"aahr_machine_learning", "aahr_computer_vision", "aahr_nlp"}
GEN_CORE = {"g_llm_zh", "g_llm_en"}
STRICT_MIN, COND_MIN, MIN_ADS, MAX_CANDIDATES = 0.30, 0.10, 30, 400
N_EXAMPLES, EXAMPLE_CHARS = 3, 150
TIER_ZH = {"strict": "严格词", "conditional": "条件词", "broad": "宽泛词"}

_matcher: AISkillMatcher | None = None
_phrases = None
_cands: set[str] = set()


def _init_worker(dictionary: str, phrases_path: str, cands: list[str]) -> None:
    global _matcher, _phrases, _cands
    from gensim.models.phrases import FrozenPhrases
    _matcher = AISkillMatcher(dictionary)
    T.init_jieba(json.loads(Path(dictionary).read_text(encoding="utf-8"))["terms"])
    _phrases = FrozenPhrases.load(phrases_path)
    _cands = set(cands)


def _example_key(rid: str, cand: str) -> int:
    return int.from_bytes(hashlib.blake2b(f"{T.SEED}|{rid}|{cand}".encode(), digest_size=8).digest(), "big")


def excerpt(clause: str, tok: str) -> str:
    """以候选词为中心截取例句，并用【】标出候选词。"""
    low = clause.lower()
    for needle in (tok, tok.replace("_", " "), tok.replace("_", "")):
        i = low.find(needle)
        if i >= 0:
            break
    else:
        return clause[:EXAMPLE_CHARS]
    j = i + len(needle)
    start = max(0, i - 50)
    end = min(len(clause), max(j + 50, start + EXAMPLE_CHARS))
    return (("…" if start else "") + clause[start:i] + "【" + clause[i:j] + "】" + clause[j:end]
            + ("…" if end < len(clause) else ""))


def _count_batch(rows: list[tuple]) -> tuple[Counter, Counter, Counter, dict]:
    """返回 n[(key, period)]、co_trad[key]（全部年份）、co_gen[key]（ChatGPT后）、例句堆。key = T:词条id 或 C:候选词。"""
    n, co_trad, co_gen = Counter(), Counter(), Counter()
    examples: dict[str, list] = {}
    for rid, title, desc, pub in rows:
        terms: set[str] = set()
        cand_clause: dict[str, str] = {}
        for clause in T.requirement_clauses(_matcher, title, desc):
            if _matcher.prefilter.search(clause):
                terms.update(t.id for t in _matcher._hits(clause))
            for tok in set(T.apply_phrases(T.tokenize_clause(clause), _phrases)) & _cands:
                cand_clause.setdefault(tok, clause)
        if not terms and not cand_clause:
            continue
        period = "na" if pub is None else ("post" if pub >= RELEASE else "pre")
        trad, gen = terms & TRAD_CORE, terms & GEN_CORE
        for key, self_id in [(f"T:{t}", t) for t in terms] + [(f"C:{c}", None) for c in cand_clause]:
            n[(key, period)] += 1
            if trad - {self_id}:
                co_trad[key] += 1
            if period == "post" and gen - {self_id}:
                co_gen[key] += 1
        for c, clause in cand_clause.items():
            heap = examples.setdefault(c, [])
            item = (-_example_key(rid, c), rid, excerpt(clause, c))  # 保留key最小的3条
            if len(heap) < N_EXAMPLES:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    return n, co_trad, co_gen, examples


def tier_for(rel: float | None, n_basis: int) -> str:
    if rel is None or n_basis < MIN_ADS:
        return "conditional"
    return "strict" if rel >= STRICT_MIN else ("conditional" if rel >= COND_MIN else "broad")


def stats_for(key: str, basis: str, n, co_trad, co_gen) -> dict:
    pre, post, na = n[(key, "pre")], n[(key, "post")], n[(key, "na")]
    total = pre + post + na
    rel_trad = co_trad[key] / total if total else None
    rel_gen = co_gen[key] / post if post else None
    rel, n_basis = (rel_gen, post) if basis == "generative" else (rel_trad, total)
    return {"n_pre": pre, "n_post": post, "n_date_missing": na, "n_all": total,
            "co_trad": co_trad[key], "rel_trad": None if rel_trad is None else round(rel_trad, 4),
            "co_gen_post": co_gen[key], "rel_gen_post": None if rel_gen is None else round(rel_gen, 4),
            "basis": basis, "n_basis": n_basis, "relevance": None if rel is None else round(rel, 4)}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--years", type=int, nargs="*", default=YEARS, help="只用于试跑；正式结果必须用全部年份")
    args = ap.parse_args()

    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    w2v_dir = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "w2v"
    out_dir = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "relevance"
    sheet_dir = Path(storage["analysis_root"]) / "ai_w2v_screening_v0.2"
    out_dir.mkdir(parents=True, exist_ok=True)
    matcher = AISkillMatcher(args.dictionary)
    with (w2v_dir / "candidates_raw.csv").open(encoding="utf-8-sig") as f:
        raw = list(csv.DictReader(f))
    print(f"RULE_VERSION={matcher.rule_version} raw_candidates={len(raw)} years={args.years}", flush=True)

    def tasks():
        for y in args.years:
            for b in pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").iter_batches(
                    batch_size=20_000, columns=[ID, TITLE, DESC, PUB]):
                d = b.to_pydict()
                yield list(zip(d[ID], d[TITLE], d[DESC], d[PUB]))

    t0 = time.time()
    n, co_trad, co_gen = Counter(), Counter(), Counter()
    examples: dict[str, list] = {}
    done = 0
    with Pool(args.workers, initializer=_init_worker,
              initargs=(str(args.dictionary), str(w2v_dir / "phrases.pkl"), [r["candidate"] for r in raw])) as pool:
        for bn, bco_t, bco_g, bex in pool.imap_unordered(_count_batch, tasks(), chunksize=1):
            n.update(bn)
            co_trad.update(bco_t)
            co_gen.update(bco_g)
            for c, items in bex.items():
                heap = examples.setdefault(c, [])
                for item in items:
                    if len(heap) < N_EXAMPLES:
                        heapq.heappush(heap, item)
                    elif item > heap[0]:
                        heapq.heapreplace(heap, item)
            done += 1
            if done % 25 == 0:
                print(f"  batches={done} ads≈{done * 20_000:,} elapsed={time.time() - t0:.0f}s", flush=True)
    print(f"COUNTED elapsed={time.time() - t0:.0f}s", flush=True)

    # 现有词
    group_of = {}
    import importlib
    groups = importlib.import_module("16_w2v_candidates").GROUPS
    for g, ids in groups.items():
        for tid in ids:
            group_of[tid] = g
    term_rows = []
    for t in matcher.terms:
        basis = "generative" if t.category == "generative" else "traditional"
        s = stats_for(f"T:{t.id}", basis, n, co_trad, co_gen)
        core = t.id in TRAD_CORE | GEN_CORE
        if t.tier == "review":
            suggested = ""
        elif core:
            suggested = "strict"
        else:
            suggested = tier_for(s["relevance"], s["n_basis"])
        term_rows.append({"term_id": t.id, "tier_v011": t.tier, "category": t.category, "group": group_of.get(t.id, ""),
                          "is_core": int(core), **s, "suggested_tier": suggested,
                          "tier_change": "" if not suggested or suggested == t.tier else f"{t.tier}→{suggested}"})
    write_csv(QC_DIR / "ai_term_relevance_v0.2.csv", term_rows)

    # 候选词
    cand_rows = []
    for r in raw:
        basis = "generative" if r["groups"] == "生成式AI" else "traditional"
        s = stats_for(f"C:{r['candidate']}", basis, n, co_trad, co_gen)
        ex = [clause for _, _, clause in sorted(examples.get(r["candidate"], []), reverse=True)]
        cand_rows.append({**r, **s, "suggested_tier": tier_for(s["relevance"], s["n_basis"]),
                          **{f"example_{i + 1}": ex[i] if i < len(ex) else "" for i in range(N_EXAMPLES)}})
    kept = [r for r in cand_rows if r["n_all"] >= MIN_ADS]
    kept.sort(key=lambda r: -float(r["max_sim"]))
    capped = kept[:MAX_CANDIDATES]
    selected = {r["candidate"] for r in capped}
    for r in cand_rows:
        r["status"] = ("selected" if r["candidate"] in selected else
                       "dropped_lt30_ads" if r["n_all"] < MIN_ADS else "dropped_over_cap")
    write_csv(out_dir / "candidates_full.csv", cand_rows)
    no_text = [{k: v for k, v in r.items() if not k.startswith("example_")} for r in cand_rows]
    write_csv(QC_DIR / "ai_w2v_candidates_v0.2.csv", no_text)

    # 筛词表（方案3.5节列；不给建议层级，避免影响人工判断）
    capped.sort(key=lambda r: (r["groups"], -float(r["max_sim"])))
    pct = lambda x: "" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    sheet = []
    for i, r in enumerate(capped, 1):
        sheet.append({"编号": i, "候选词": r["candidate"], "来源组": r["groups"], "最高相似度": r["max_sim"],
                      "最接近的种子词": r["best_seed"], "出现广告数_ChatGPT前": r["n_pre"],
                      "出现广告数_ChatGPT后": r["n_post"], "共现相关度": pct(r["relevance"]),
                      "相关度口径": "生成式AI核心词，ChatGPT后" if r["basis"] == "generative" else "传统AI核心词，全部年份",
                      "例句1": r["example_1"], "例句2": r["example_2"], "例句3": r["example_3"],
                      "筛选结果(1严格/2条件/3宽泛/0不加入)": "", "备注": ""})
    for who in ("A", "B"):
        write_csv(sheet_dir / f"筛词表_{who}.csv", sheet)

    summary = {
        "rule_version_input": matcher.rule_version, "years": args.years,
        "thresholds": {"strict_min": STRICT_MIN, "conditional_min": COND_MIN, "min_ads": MIN_ADS,
                       "max_candidates": MAX_CANDIDATES},
        "core_terms": {"traditional": sorted(TRAD_CORE), "generative": sorted(GEN_CORE)},
        "candidates_raw": len(raw), "candidates_ge30_ads": len(kept), "candidates_in_sheet": len(capped),
        "existing_term_tier_changes": Counter(r["tier_change"] for r in term_rows if r["tier_change"]),
        "candidate_suggested_tiers": Counter(r["suggested_tier"] for r in capped),
        "elapsed_seconds": round(time.time() - t0),
    }
    (QC_DIR / "ai_term_relevance_v0.2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"SHEETS → {sheet_dir}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
