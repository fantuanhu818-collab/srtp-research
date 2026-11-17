"""根据人工标注计算AI技能识别的一致率、查准率和查全率。

输入：<analysis_root>/ai_annotation_v1/ 下填好的 标注表_A.csv、标注表_B.csv、annotation_key.csv，
      可选 分歧裁定.csv（列：编号, 最终标注），以及 outputs/qc/ai_annotation_v1_strata.csv（各层总体数）。
输出：outputs/qc/ai_annotation_v1_metrics.csv（指标，无原文，进Git）
      <analysis_root>/ai_annotation_v1/分歧清单.csv、误判漏判清单.csv（含原文，不进Git）

指标按分层抽样权重换算到总体：某层的“真AI比例”乘以该层总体数，加总得到总体真AI数。
  查准率 = 程序判1的广告中真AI的比例；查全率 = 真AI广告中被程序判1的比例。
标注值9（无法判断）不进入指标，单独报告数量。

用法：.venv/bin/python code/python/15_score_annotation.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LABEL = "是否要求AI技能(1/0/9)"
POSITIVE_STRATA = {"strict": ["strict_hit"], "broad": ["strict_hit", "broad_only"]}


def read_sheet(path: Path) -> pd.Series:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={LABEL: "string"})
    labels = pd.to_numeric(df[LABEL].str.strip(), errors="coerce")
    bad = df.loc[labels.isna() | ~labels.isin([0, 1, 9]), "编号"].tolist()
    if bad:
        raise SystemExit(f"{path.name} 有未填写或取值不是1/0/9的行，编号：{bad[:20]}{'…' if len(bad) > 20 else ''}")
    return pd.Series(labels.astype(int).values, index=df["编号"])


def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    po = (a == b).mean()
    pe = sum((a == k).mean() * (b == k).mean() for k in (0, 1))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def totals(labeled: pd.DataFrame, pop: pd.DataFrame, version: str) -> tuple[float, float, float, int]:
    """一个时期内：(程序判1中的真AI估计数, 程序判1总数, 真AI估计总数, 总体数)。"""
    rates = labeled.groupby("stratum")["label"].mean()
    counts = pop.set_index("stratum")["population"]
    pos = POSITIVE_STRATA[version]
    true_total = sum(counts[s] * rates.get(s, 0.0) for s in counts.index)
    true_pos = sum(counts[s] * rates.get(s, 0.0) for s in pos)
    return true_pos, sum(counts[s] for s in pos), true_total, int(counts.sum())


def main() -> int:
    storage = json.loads((PROJECT_ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
    d = Path(storage["analysis_root"]) / "ai_annotation_v1"
    key = pd.read_csv(d / "annotation_key.csv", encoding="utf-8-sig").set_index("annotation_no")
    a, b = read_sheet(d / "标注表_A.csv"), read_sheet(d / "标注表_B.csv")

    # 1. 重叠样本一致性
    both = a.index.intersection(b.index)
    pair = pd.DataFrame({"A": a[both], "B": b[both]})
    usable = pair[(pair.A != 9) & (pair.B != 9)]
    agree = (usable.A == usable.B).mean()
    kappa = cohen_kappa(usable.A, usable.B)
    print(f"OVERLAP n={len(pair)} usable={len(usable)} agreement={agree:.3f} kappa={kappa:.3f}")

    # 2. 最终标注：一致取一致值；分歧看裁定文件
    final = pd.concat([a.drop(both), b.drop(both)])
    disagree = pair[pair.A != pair.B]
    resolved = {}
    if (d / "分歧裁定.csv").exists():
        r = pd.read_csv(d / "分歧裁定.csv", encoding="utf-8-sig")
        resolved = dict(zip(r["编号"], r["最终标注"].astype(int)))
    for n, row in pair.iterrows():
        if row.A == row.B:
            final[n] = row.A
        elif n in resolved:
            final[n] = resolved[n]
    unresolved = [n for n in disagree.index if n not in resolved]
    if unresolved:
        key.loc[unresolved].assign(A=pair.A, B=pair.B).to_csv(d / "分歧清单.csv", encoding="utf-8-sig")
        print(f"UNRESOLVED={len(unresolved)}：已写入分歧清单.csv，裁定后填写 分歧裁定.csv（编号, 最终标注）再运行；未裁定的暂不计入指标")

    labeled = key.join(final.rename("label"), how="inner")
    n_unsure = int((labeled.label == 9).sum())
    labeled = labeled[labeled.label.isin([0, 1])]

    # 3. 加权查准率、查全率：每个时期单独加权，合计时把两个时期的估计数相加
    strata = pd.read_csv(PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v1_strata.csv", encoding="utf-8-sig")
    rows = []
    for version in ("strict", "broad"):
        per = {p: totals(labeled[labeled.period == p], strata[strata.period == p], version) for p in ("pre", "post")}
        per["all"] = tuple(map(sum, zip(per["pre"], per["post"])))
        for period, (tp, pt, tt, n) in per.items():
            rows.append({"period": period, "version": version,
                         "n_labeled": int((labeled.period == period).sum()) if period != "all" else len(labeled),
                         "precision": tp / pt if pt else None, "recall": tp / tt if tt else None,
                         "est_true_ai_share": tt / n if n else None})
    metrics = pd.DataFrame(rows)
    by_stratum = labeled.groupby(["period", "stratum"])["label"].agg(n="size", true_ai_share="mean").reset_index()
    out = PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v1_metrics.csv"
    pd.concat([metrics.assign(kind="overall"), by_stratum.assign(kind="by_stratum"),
               pd.DataFrame([{"kind": "agreement", "n_labeled": len(usable), "precision": agree, "recall": kappa,
                              "version": "A_vs_B（precision列=一致率，recall列=kappa）"},
                             {"kind": "unsure_label_9", "n_labeled": n_unsure}])]).to_csv(out, index=False, encoding="utf-8-sig")
    print(metrics.round(3).to_string(index=False))
    print(by_stratum.round(3).to_string(index=False))

    # 4. 误判（程序1、人工0）按命中词统计；漏判（程序0、人工1）按层列出
    fp = labeled[(labeled.stratum == "strict_hit") & (labeled.label == 0)]
    fn = labeled[(labeled.stratum != "strict_hit") & (labeled.label == 1)]
    print("FALSE_POSITIVE_TERMS", fp.ai_hit_terms.str.split("|").explode().value_counts().to_dict())
    print("FALSE_NEGATIVE_BY_STRATUM", fn.stratum.value_counts().to_dict())
    pd.concat([fp.assign(error="误判FP"), fn.assign(error="漏判FN")]).to_csv(d / "误判漏判清单.csv", encoding="utf-8-sig")
    print(f"METRICS -> {out}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
