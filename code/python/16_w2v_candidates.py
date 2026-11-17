"""规则v0.2第2步：训练Word2Vec，从种子词找候选新词。

方案：docs/AI技能识别调整方案与对接_2026-11-16.md 第3节。
  语料：每年随机15万条 + v0.1.1严格或宽泛命中的全部广告，去重；只用岗位名称和非公司介绍句。
  分词：jieba + 自定义词典，英文小写，Phrases合并英文词组。
  模型：Skip-gram，200维，窗口5，最低词频20，5轮，随机种子20261116。
  候选：每个种子词取余弦相似度最高的20个，保留≥0.55，去掉已被现有词典覆盖的词。

输入（只读）：<curated_root>/cleaned_v1、<features_root>/ai_skill_v1
输出（不进Git，含模型和语料）：<features_root>/ai_skill_v0.2_work/w2v/
  sample_ids.csv、corpus_raw.txt、phrases.pkl、corpus.txt、w2v.model、seeds.csv、candidates_raw.csv
输出（进Git，无广告原文）：outputs/qc/ai_w2v_seeds_v0.2.csv、outputs/qc/ai_w2v_candidates_raw_v0.2.csv

模型只训练一次：w2v.model 已存在时直接读取，不重新训练（--force-retrain 例外）。
出现广告数≥30、最多400个的筛选和相关度在 17_term_relevance.py 中完成。

运行：.venv/bin/python code/python/16_w2v_candidates.py
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_w2v_text as T  # noqa: E402
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
PER_YEAR = 150_000
ID, TITLE, DESC = "来源记录ID", "招聘岗位", "职位描述"
W2V = dict(sg=1, vector_size=200, window=5, min_count=20, epochs=5)
TOPN, MIN_SIM = 20, 0.55

# 方案3.4节的7组种子词（现有55个严格词）
GROUPS = {
    "机器学习方法": ["aahr_machine_learning", "aahr_supervised_learning", "aahr_unsupervised_learning", "aahr_svm",
               "aahr_random_forests", "aahr_gradient_boosting", "aahr_kernel_methods", "aahr_lsa", "aahr_lda",
               "x_ml_algorithms"],
    "深度学习": ["aahr_deep_learning", "aahr_neural_networks", "x_reinforcement_learning", "x_nn_architectures", "x_gan"],
    "计算机视觉": ["aahr_computer_vision", "aahr_machine_vision", "aahr_image_recognition", "aahr_object_recognition",
              "aahr_pattern_recognition", "aahr_image_processing", "x_cv_tasks"],
    "语言与语音": ["aahr_nlp", "aahr_speech_recognition", "aahr_text_mining", "aahr_sentiment_analysis",
              "aahr_sentiment_classification", "aahr_machine_translation", "aahr_word2vec", "x_speech_synthesis",
              "aahr_ai_chatbot", "aahr_virtual_agents"],
    "推荐与搜索": ["aahr_recommender_systems", "x_ctr", "x_knowledge_graph"],
    "工具框架": ["aahr_keras", "aahr_opencv", "aahr_xgboost", "aahr_libsvm", "aahr_mahout", "x_ml_frameworks"],
    "生成式AI": ["g_llm_zh", "g_llm_en", "g_genai", "g_aigc", "g_chatgpt", "g_gpt", "g_cn_llm_products",
              "g_image_gen_tools", "g_copilot", "g_prompt_eng", "g_rag", "g_llm_frameworks", "g_agent", "g_finetune"],
}

_matcher: AISkillMatcher | None = None


def _init_worker(dictionary: str) -> None:
    global _matcher
    _matcher = AISkillMatcher(dictionary)
    T.init_jieba(json.loads(Path(dictionary).read_text(encoding="utf-8"))["terms"])


def _tokenize_batch(rows: list[tuple[str, str]]) -> list[str]:
    lines = []
    for title, desc in rows:
        for clause in T.requirement_clauses(_matcher, title, desc):
            toks = T.tokenize_clause(clause)
            if sum(t != T.BREAK for t in toks) >= 2:
                lines.append(" ".join(toks))
    return lines


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def build_sample(curated: Path, ai_dir: Path, out: Path) -> dict[int, set[str]]:
    """每年随机15万条（按ID排序后用固定种子抽，可复现）+ v0.1.1命中广告。"""
    con = duckdb.connect()
    picked: dict[int, set[str]] = {}
    rows = []
    for y in YEARS:
        ids = sorted(con.execute(f"SELECT {ID} FROM read_parquet('{sql_path(curated / f'jobs_{y}_cleaned.parquet')}')"
                                 ).fetchnumpy()[ID].tolist())
        rand = set(random.Random(T.SEED + y).sample(ids, min(PER_YEAR, len(ids))))
        hits = set(con.execute(f"SELECT source_record_id FROM read_parquet('{sql_path(ai_dir / f'jobs_{y}_ai_skill.parquet')}') "
                               f"WHERE ai_skill = 1 OR ai_skill_broad = 1").fetchnumpy()["source_record_id"].tolist())
        picked[y] = rand | hits
        rows += [(y, i, int(i in rand), int(i in hits)) for i in sorted(picked[y])]
        print(f"SAMPLE {y}: random={len(rand)} hits={len(hits)} union={len(picked[y])}", flush=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "source_record_id", "in_random", "in_v011_hits"])
        w.writerows(rows)
    return picked


def load_sample(path: Path) -> dict[int, set[str]]:
    picked: dict[int, set[str]] = {y: set() for y in YEARS}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            picked[int(r["year"])].add(r["source_record_id"])
    return picked


def write_raw_corpus(curated: Path, picked: dict[int, set[str]], out: Path, dictionary: Path, workers: int) -> None:
    def tasks():
        for y in YEARS:
            for b in pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").iter_batches(
                    batch_size=20_000, columns=[ID, TITLE, DESC]):
                d = b.to_pydict()
                keep = [(t, s) for i, t, s in zip(d[ID], d[TITLE], d[DESC]) if i in picked[y]]
                if keep:
                    yield keep
    tmp = out.with_suffix(".tmp")
    n = 0
    with Pool(workers, initializer=_init_worker, initargs=(str(dictionary),)) as pool, \
            tmp.open("w", encoding="utf-8") as f:
        # imap（保持顺序）保证语料文件逐行可复现
        for lines in pool.imap(_tokenize_batch, tasks(), chunksize=1):
            f.writelines(line + "\n" for line in lines)
            n += len(lines)
    tmp.replace(out)
    print(f"CORPUS_RAW lines={n}", flush=True)


def train_phrases(raw: Path, out: Path):
    from gensim.models.phrases import Phrases

    def runs():
        with raw.open(encoding="utf-8") as f:
            for line in f:
                yield from T.ascii_runs(line.split())
    phrases = Phrases(runs(), min_count=20, threshold=10, delimiter="_").freeze()
    phrases.save(str(out))
    print(f"PHRASES n={len(phrases.phrasegrams)}", flush=True)
    return phrases


def write_corpus(raw: Path, phrases, out: Path) -> None:
    n = 0
    with raw.open(encoding="utf-8") as fin, out.with_suffix(".tmp").open("w", encoding="utf-8") as fout:
        for line in fin:
            toks = T.apply_phrases(line.split(), phrases)
            if len(toks) >= 2:
                fout.write(" ".join(toks) + "\n")
                n += 1
    out.with_suffix(".tmp").replace(out)
    print(f"CORPUS lines={n}", flush=True)


def covered_by_dictionary(token: str, matcher: AISkillMatcher) -> str:
    """候选词若已被现有任一词条（含宽泛、待审）匹配，返回该词条id。"""
    text = token.replace("_", " ")
    for form in (text, text.upper()):
        for term in matcher.terms:
            if term.regex.search(form):
                return term.id
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--force-retrain", action="store_true")
    args = ap.parse_args()

    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    ai_dir = Path(storage["features_root"]) / "ai_skill_v1"
    work = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "w2v"
    work.mkdir(parents=True, exist_ok=True)
    matcher = AISkillMatcher(args.dictionary)
    t0 = time.time()

    from gensim.models import Word2Vec
    from gensim.models.phrases import FrozenPhrases

    model_path = work / "w2v.model"
    if model_path.exists() and not args.force_retrain:
        print("W2V model exists, loading (不重新训练)", flush=True)
        model = Word2Vec.load(str(model_path))
    else:
        sample_path = work / "sample_ids.csv"
        picked = load_sample(sample_path) if sample_path.exists() else build_sample(curated, ai_dir, sample_path)
        raw = work / "corpus_raw.txt"
        if not raw.exists():
            write_raw_corpus(curated, picked, raw, args.dictionary, args.workers)
        ph_path = work / "phrases.pkl"
        phrases = FrozenPhrases.load(str(ph_path)) if ph_path.exists() else train_phrases(raw, ph_path)
        corpus = work / "corpus.txt"
        if not corpus.exists():
            write_corpus(raw, phrases, corpus)
        print(f"TRAIN W2V {W2V} elapsed={time.time() - t0:.0f}s", flush=True)
        model = Word2Vec(corpus_file=str(corpus), workers=args.workers, seed=T.SEED, **W2V)
        model.save(str(model_path))
    wv = model.wv
    print(f"VOCAB size={len(wv)} elapsed={time.time() - t0:.0f}s", flush=True)

    # 种子：词表中完整匹配某个严格词正则的词
    by_id = {t.id: t for t in matcher.terms}
    group_of = {tid: g for g, ids in GROUPS.items() for tid in ids}
    strict_ids = {t.id for t in matcher.terms if t.tier == "strict"}
    assert strict_ids == set(group_of), f"分组与严格词不一致：{strict_ids ^ set(group_of)}"
    seeds = []  # (token, term_id, group)
    for tok in wv.index_to_key:
        text = tok.replace("_", " ")
        for tid, g in group_of.items():
            if by_id[tid].regex.fullmatch(text):
                seeds.append((tok, tid, g))
                break
    with (work / "seeds.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seed_token", "term_id", "group", "w2v_count"])
        w.writerows((s, tid, g, wv.get_vecattr(s, "count")) for s, tid, g in seeds)
    missing = strict_ids - {tid for _, tid, _ in seeds}
    print(f"SEEDS tokens={len(seeds)} terms={len(strict_ids) - len(missing)}/{len(strict_ids)} "
          f"missing={sorted(missing)}", flush=True)

    # 近邻
    seed_tokens = {s for s, _, _ in seeds}
    cand: dict[str, dict] = {}
    covered_cache: dict[str, str] = {}
    for s, tid, g in seeds:
        for tok, sim in wv.most_similar(s, topn=TOPN):
            if sim < MIN_SIM or tok in seed_tokens:
                continue
            if tok not in covered_cache:
                covered_cache[tok] = covered_by_dictionary(tok, matcher)
            if covered_cache[tok]:
                continue
            c = cand.setdefault(tok, {"groups": set(), "seeds": [], "max_sim": 0.0, "best_seed": ""})
            c["groups"].add(g)
            c["seeds"].append((sim, s))
            if sim > c["max_sim"]:
                c["max_sim"], c["best_seed"] = sim, s
    n_covered = sum(1 for v in covered_cache.values() if v)
    rows = []
    for tok, c in sorted(cand.items(), key=lambda kv: -kv[1]["max_sim"]):
        top = [s for _, s in sorted(c["seeds"], reverse=True)[:5]]
        rows.append({"candidate": tok, "groups": ";".join(sorted(c["groups"])), "max_sim": round(c["max_sim"], 4),
                     "best_seed": c["best_seed"], "n_seeds": len(c["seeds"]), "top_seeds": ";".join(top),
                     "w2v_count": wv.get_vecattr(tok, "count")})
    for path in (work / "candidates_raw.csv", QC_DIR / "ai_w2v_candidates_raw_v0.2.csv"):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (QC_DIR / "ai_w2v_seeds_v0.2.csv").write_bytes((work / "seeds.csv").read_bytes())
    print(f"CANDIDATES n={len(rows)} (已被现有词覆盖而去掉 {n_covered} 个) elapsed={time.time() - t0:.0f}s")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
