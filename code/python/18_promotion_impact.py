"""评估“宽泛词按相关度门槛升为严格词”会改变多少条广告（规则v0.2决策用）。

做法：把 ai_term_relevance_v0.2.csv 中 tier_change = broad→strict 的词改成严格词，其余规则不变，
在全样本 cleaned_v1 上重跑 ai_skill_matcher；与 v0.1.1 结果（ai_skill_v1）逐条对比，
统计 ai_skill 由 0 变 1 的广告（只看升级的影响，不含降级）。

输出（进Git，无原文）：outputs/qc/ai_promotion_impact_v0.2_terms.csv   每个升级词新增的阳性广告数
                      outputs/qc/ai_promotion_impact_v0.2_years.csv   各方案各年份的AI占比
输出（不进Git，含原句）：<features_root>/ai_skill_v0.2_work/promotion/flipped_ads.csv、examples.csv

运行：.venv/bin/python code/python/18_promotion_impact.py
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_skill_matcher import DEFAULT_DICTIONARY, AISkillMatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
YEARS = list(range(2018, 2026))
ID, TITLE, DESC, PUB, SRC = "来源记录ID", "招聘岗位", "职位描述", "招聘发布日期", "来源"
RELEASE = date(2022, 11, 30)
SEED = 20261116
N_EXAMPLES = 10
# 折中方案的预设分组（按第5.1节“词本身指一种AI方法、模型、工具或任务”初步划分，待A、B确认）
TECHNICAL = {"b_cnn", "b_lora", "b_transformer", "b_prompt", "b_tts", "b_ml_abbr", "b_cv_abbr", "b_llm_bare"}

_matcher: AISkillMatcher | None = None
_promoted: set[str] = set()


def _init(dict_path: str, promoted: list[str]) -> None:
    global _matcher, _promoted
    _matcher = AISkillMatcher(dict_path)
    _promoted = set(promoted)


def _run(rows: list[tuple]) -> list[tuple]:
    out = []
    for rid, title, desc, pub, src, old in rows:
        if old != 0:
            continue
        r = _matcher.classify(title, desc)
        if r["ai_skill"] == 1:
            hits = set(r["ai_hit_terms"].split("|")) & _promoted
            period = "na" if pub is None else ("post" if pub >= RELEASE else "pre")
            out.append((rid, pub.year if pub else None, period, src, "|".join(sorted(hits)), r["ai_evidence"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    curated = Path(storage["curated_root"]) / "cleaned_v1"
    ai_dir = Path(storage["features_root"]) / "ai_skill_v1"
    out_dir = Path(storage["features_root"]) / "ai_skill_v0.2_work" / "promotion"
    out_dir.mkdir(parents=True, exist_ok=True)

    with (QC_DIR / "ai_term_relevance_v0.2.csv").open(encoding="utf-8-sig") as f:
        rel = {r["term_id"]: r for r in csv.DictReader(f)}
    promoted = sorted(t for t, r in rel.items() if r["tier_change"] == "broad→strict")
    assert TECHNICAL <= set(promoted), TECHNICAL - set(promoted)
    spec = json.loads(DEFAULT_DICTIONARY.read_text(encoding="utf-8"))
    for t in spec["terms"]:
        if t["id"] in promoted:
            t["tier"] = "strict"
    tmp = Path(tempfile.mkstemp(suffix=".json")[1])
    tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    print(f"PROMOTED {len(promoted)}: {promoted}", flush=True)

    totals = defaultdict(Counter)  # (year) -> judged / old_pos
    def tasks():
        for y in YEARS:
            a = pq.read_table(ai_dir / f"jobs_{y}_ai_skill.parquet", columns=["source_record_id", "ai_skill"]).to_pydict()
            old = dict(zip(a["source_record_id"], a["ai_skill"]))
            for s in a["ai_skill"]:
                if s is not None:
                    totals[y]["judged"] += 1
                    totals[y]["old_pos"] += s
            del a
            for b in pq.ParquetFile(curated / f"jobs_{y}_cleaned.parquet").iter_batches(
                    batch_size=20_000, columns=[ID, TITLE, DESC, PUB, SRC]):
                d = b.to_pydict()
                yield list(zip(d[ID], d[TITLE], d[DESC], d[PUB], d[SRC], [old[i] for i in d[ID]]))

    t0 = time.time()
    flipped = []
    with Pool(args.workers, initializer=_init, initargs=(str(tmp), promoted)) as pool:
        for res in pool.imap_unordered(_run, tasks(), chunksize=1):
            flipped.extend(res)
    tmp.unlink()
    print(f"FLIPPED {len(flipped)} elapsed={time.time() - t0:.0f}s", flush=True)

    with (out_dir / "flipped_ads.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_record_id", "year", "period", "来源", "promoted_hits", "evidence"])
        w.writerows(flipped)

    old_pos = sum(c["old_pos"] for c in totals.values())
    judged = sum(c["judged"] for c in totals.values())
    term_rows = []
    for t in promoted:
        mine = [f for f in flipped if t in f[4].split("|")]
        only = [f for f in mine if f[4] == t]
        term_rows.append({"term_id": t, "group": "technical" if t in TECHNICAL else "generic",
                          "relevance": rel[t]["relevance"], "n_ads_with_term": rel[t]["n_all"],
                          "flips_any": len(mine), "flips_only_this_term": len(only),
                          "flips_pre": sum(f[2] == "pre" for f in mine), "flips_post": sum(f[2] == "post" for f in mine),
                          "flips_pct_of_v011_positives": round(len(mine) / old_pos * 100, 1)})
    term_rows.sort(key=lambda r: -r["flips_any"])
    with (QC_DIR / "ai_promotion_impact_v0.2_terms.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(term_rows[0]))
        w.writeheader()
        w.writerows(term_rows)

    scenarios = {"v0.1.1": set(), "technical_only": TECHNICAL, "all_promoted": set(promoted)}
    year_rows = []
    for y in YEARS:
        row = {"year": y, "judged": totals[y]["judged"]}
        for name, terms in scenarios.items():
            add = sum(1 for f in flipped if f[1] == y and set(f[4].split("|")) & terms) if terms else 0
            row[f"{name}_rate_pct"] = round((totals[y]["old_pos"] + add) / totals[y]["judged"] * 100, 3)
            row[f"{name}_positives"] = totals[y]["old_pos"] + add
        year_rows.append(row)
    all_row = {"year": "all", "judged": judged}
    for name, terms in scenarios.items():
        add = sum(1 for f in flipped if set(f[4].split("|")) & terms) if terms else 0
        all_row[f"{name}_rate_pct"] = round((old_pos + add) / judged * 100, 3)
        all_row[f"{name}_positives"] = old_pos + add
    year_rows.append(all_row)
    with (QC_DIR / "ai_promotion_impact_v0.2_years.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_row))
        w.writeheader()
        w.writerows(year_rows)

    rng = random.Random(SEED)
    with (out_dir / "examples.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["term_id", "period", "source_record_id", "evidence"])
        for t in promoted:
            only = sorted((f for f in flipped if f[4] == t), key=lambda f: f[0])
            for period in ("pre", "post"):
                pool_ = [f for f in only if f[2] == period]
                for fl in rng.sample(pool_, min(N_EXAMPLES // 2, len(pool_))):
                    w.writerow([t, period, fl[0], fl[5]])
    for r in term_rows:
        print(r)
    for r in year_rows:
        print(r)
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
