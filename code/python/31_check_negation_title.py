"""核对11-19两条口径修改的影响：否定表达、岗位名称不单独决定ai_skill。

只重判 ai_skill_v1 中 ai_skill_broad=1 的广告（其余广告没有任何AI词，结果不会变）。
分别关掉/打开两条规则，统计各年有多少广告的 ai_skill、ai_skill_broad 发生变化。

输出：outputs/qc/ai_negation_title_impact_v0.2.csv（汇总数字，进Git）
      <analysis_root>/ai_negation_title_examples.csv（含原文的抽样，不进Git）
用法：.venv/bin/python code/python/31_check_negation_title.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "python"))
from ai_skill_matcher import AISkillMatcher  # noqa: E402

DICT = ROOT / "config" / "ai_skill_dictionary_v0.2_draft.json"
storage = json.loads((ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
FEAT = Path(storage["features_root"]) / "ai_skill_v1"
CLEAN = Path(storage["curated_root"]) / "cleaned_v1"
YEARS = range(2018, 2026)


def variants() -> dict[str, AISkillMatcher]:
    """old：两条都关（等于现有结果）；neg：只加否定；title：只改标题；new：两条都开。"""
    out = {}
    for name, neg, title_strict in [("old", False, True), ("neg", True, True),
                                    ("title", False, False), ("new", True, False)]:
        m = AISkillMatcher(DICT)
        if not neg:
            m.neg_prefix = m.neg_suffix = None
        m.title_counts_strict = title_strict
        out[name] = m
    return out


def one_year(year: int) -> tuple[list[dict], pd.DataFrame]:
    ai = pd.read_parquet(FEAT / f"jobs_{year}_ai_skill.parquet", columns=["source_record_id", "ai_skill", "ai_skill_broad"])
    ids = set(ai.loc[ai.ai_skill_broad == 1, "source_record_id"])
    raw = pd.read_parquet(CLEAN / f"jobs_{year}_cleaned.parquet", columns=["来源记录ID", "招聘岗位", "职位描述"])
    raw = raw[raw["来源记录ID"].isin(ids)]
    ms = variants()
    res = {k: [m.classify(t, d) for t, d in zip(raw["招聘岗位"], raw["职位描述"])] for k, m in ms.items()}
    df = raw.rename(columns={"来源记录ID": "source_record_id"}).reset_index(drop=True)
    for k, rs in res.items():
        df[f"{k}_s"] = [r["ai_skill"] for r in rs]
        df[f"{k}_b"] = [r["ai_skill_broad"] for r in rs]
    total = len(ai)
    rows = []
    for k in ("neg", "title", "new"):
        rows.append({
            "year": year, "variant": k, "total_ads": total, "rechecked_ads": len(df),
            "strict_old": int(df.old_s.sum()), "strict_new": int(df[f"{k}_s"].sum()),
            "strict_lost": int(((df.old_s == 1) & (df[f"{k}_s"] == 0)).sum()),
            "strict_gained": int(((df.old_s == 0) & (df[f"{k}_s"] == 1)).sum()),
            "broad_lost": int(((df.old_b == 1) & (df[f"{k}_b"] == 0)).sum()),
        })
    changed = df[(df.old_s != df.new_s) | (df.old_b != df.new_b)].copy()
    changed["reason"] = ["negation" if neg else "title" for neg in ((changed.old_s != changed.neg_s) | (changed.old_b != changed.neg_b))]
    changed["year"] = year
    return rows, changed.sample(min(len(changed), 40), random_state=20261119)


def main() -> int:
    with ProcessPoolExecutor(max_workers=7) as ex:
        results = list(ex.map(one_year, YEARS))
    rows = [r for rs, _ in results for r in rs]
    t = pd.DataFrame(rows)
    tot = t.groupby("variant", as_index=False)[["total_ads", "rechecked_ads", "strict_old", "strict_new",
                                                 "strict_lost", "strict_gained", "broad_lost"]].sum()
    tot["year"] = "all"
    t = pd.concat([t, tot], ignore_index=True)
    t["strict_rate_old"] = t.strict_old / t.total_ads
    t["strict_rate_new"] = t.strict_new / t.total_ads
    out = ROOT / "outputs" / "qc" / "ai_negation_title_impact_v0.2.csv"
    t.to_csv(out, index=False, encoding="utf-8-sig")
    ex_path = Path(storage["analysis_root"]) / "ai_negation_title_examples.csv"
    pd.concat([e for _, e in results]).to_csv(ex_path, index=False, encoding="utf-8-sig")
    print(t[t.year == "all"].round(5).to_string(index=False))
    print(f"IMPACT={out}\nEXAMPLES={ex_path}\nPYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
