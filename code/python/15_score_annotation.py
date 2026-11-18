"""根据人工标注计算AI技能识别的一致率、查准率和查全率。

输入：<analysis_root>/ai_annotation_v0.2/ 下填好的 标注表_A.csv、标注表_B.csv、annotation_key.csv，
      可选 分歧裁定.csv（列：编号, 最终标注），以及 outputs/qc/ai_annotation_v0.2_strata.csv（各层总体数）。
输出：outputs/qc/ai_annotation_v0.2_metrics.csv（指标，无原文，进Git）
      <analysis_root>/ai_annotation_v0.2/分歧清单.csv、误判漏判清单.csv（含原文，不进Git）

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
AI_TYPE = "AI类型(traditional/generative/both)"
COLUMNS = ["编号", "招聘岗位", "职位描述", LABEL, AI_TYPE, "备注"]
AI_TYPES = {"traditional", "generative", "both"}
NOTE_TAGS = ["仅专业", "标注类", "AI工具使用", "仅标题", "仅算法岗"]
POSITIVE_STRATA = {"strict": ["strict_hit", "new_terms_only"],
                   "broad": ["strict_hit", "new_terms_only", "conditional_only", "broad_only"]}

# 误判漏判的错误原因代码（对齐说明第3.10节）。由Agent对照原文填写，人工标注本身不改。
ERROR_CODES = {
    "company_intro": "AI词只在公司或产品介绍里，程序没识别出是介绍",
    "homonym": "同形异义：AI指Illustrator、CV指简历、Transformer指变压器等",
    "generic_mention": "泛泛提到AI，不构成技能要求（如“熟悉人工智能行业”）",
    "negation": "否定表达：无需、不要求、非必须",
    "conditional_unpaired": "条件词没有搭配另一个AI词，程序未计入",
    "missing_term": "词典漏词或缺少常见写法",
    "exclusion_overreach": "排除规则误伤了真正的AI要求",
    "exclusion_missing": "缺少应有的排除规则",
    "tool_use": "只是使用AI工具，口径待定",
    "label_dispute": "人工标注可能有误，建议两人复核（不改标注）",
}


def check_sheet(df: pd.DataFrame, name: str, expected: set) -> None:
    """交回前质量检查（对齐说明第3.11节）。有问题就停下并列出编号，不自动修改。"""
    problems = []
    if list(df.columns) != COLUMNS:
        problems.append(f"列名或顺序被改动：{list(df.columns)}")
    if set(df["编号"]) != expected or df["编号"].duplicated().any():
        problems.append("编号与发出的标注表不一致（有增删或重复）")
    # 转成普通浮点数：空白为NaN，避免可空类型在逻辑运算里报错
    labels = pd.to_numeric(df[LABEL].astype("string").str.strip(), errors="coerce").astype(float)
    bad = df.loc[(labels.isna() | ~labels.isin([0, 1, 9])).to_numpy(), "编号"].tolist()
    if bad:
        problems.append(f"未填写或取值不是1/0/9：{bad[:20]}")
    types = df[AI_TYPE].fillna("").astype(str).str.strip().str.lower()
    no_type = df.loc[(labels == 1).to_numpy() & ~types.isin(AI_TYPES).to_numpy(), "编号"].tolist()
    if no_type:
        problems.append(f"标1但AI类型没填或不是traditional/generative/both：{no_type[:20]}")
    extra_type = df.loc[labels.isin([0, 9]).to_numpy() & (types != "").to_numpy(), "编号"].tolist()
    if extra_type:
        problems.append(f"标0或9但填了AI类型（应留空）：{extra_type[:20]}")
    if problems:
        raise SystemExit(f"{name} 未通过交回前检查：\n  - " + "\n  - ".join(problems))


def read_sheet(stem: Path, expected: set) -> pd.Series:
    """优先读Excel版（32_make_annotation_xlsx.py生成的“标注”页），没有再读CSV。"""
    xlsx, csv = stem.with_suffix(".xlsx"), stem.with_suffix(".csv")
    if xlsx.exists():
        path = xlsx
        df = pd.read_excel(xlsx, sheet_name="标注", dtype=str)
        df["编号"] = pd.to_numeric(df["编号"]).astype(int)
        df[LABEL] = df[LABEL].str.replace(r"\.0$", "", regex=True)
    else:
        path = csv
        df = pd.read_csv(csv, encoding="utf-8-sig", dtype={LABEL: "string", AI_TYPE: "string", "备注": "string"})
    check_sheet(df, path.name, expected)
    labels = pd.to_numeric(df[LABEL].astype("string").str.strip(), errors="coerce")
    print(f"READ {path.name}")
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
    d = Path(storage["analysis_root"]) / "ai_annotation_v0.2"
    key = pd.read_csv(d / "annotation_key.csv", encoding="utf-8-sig").set_index("annotation_no")
    who = key["annotator"]
    a = read_sheet(d / "标注表_A", set(key.index[who.isin(["A", "A+B"])]))
    b = read_sheet(d / "标注表_B", set(key.index[who.isin(["B", "A+B"])]))

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
    strata = pd.read_csv(PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v0.2_strata.csv", encoding="utf-8-sig")
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
    out = PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v0.2_metrics.csv"
    pd.concat([metrics.assign(kind="overall"), by_stratum.assign(kind="by_stratum"),
               pd.DataFrame([{"kind": "agreement", "n_labeled": len(usable), "precision": agree, "recall": kappa,
                              "version": "A_vs_B（precision列=一致率，recall列=kappa）"},
                             {"kind": "unsure_label_9", "n_labeled": n_unsure}])]).to_csv(out, index=False, encoding="utf-8-sig")
    print(metrics.round(3).to_string(index=False))
    print(by_stratum.round(3).to_string(index=False))

    # 4. 误判（程序1、人工0）按命中词统计；漏判（程序0、人工1）按层列出
    fp = labeled[labeled.stratum.isin(POSITIVE_STRATA["strict"]) & (labeled.label == 0)]
    fn = labeled[~labeled.stratum.isin(POSITIVE_STRATA["strict"]) & (labeled.label == 1)]
    print("FALSE_POSITIVE_TERMS", fp.ai_hit_terms.str.split("|").explode().value_counts().to_dict())
    print("FALSE_NEGATIVE_BY_STRATUM", fn.stratum.value_counts().to_dict())
    # 留空两列给Agent：错误原因代码（只能用ERROR_CODES里的代码）、建议复核（只写建议，不改人工标注）
    errors = pd.concat([fp.assign(error="误判FP"), fn.assign(error="漏判FN")]).assign(错误原因代码="", 建议复核="")
    errors.to_csv(d / "误判漏判清单.csv", encoding="utf-8-sig")
    pd.DataFrame(ERROR_CODES.items(), columns=["错误原因代码", "含义"]).to_csv(
        d / "错误原因代码表.csv", index=False, encoding="utf-8-sig")
    coded = d / "误判漏判清单_已归因.csv"
    if coded.exists():  # Agent填好后另存为此文件，再运行本程序即汇总，不含原文，进Git
        c = pd.read_csv(coded, encoding="utf-8-sig", dtype={"错误原因代码": "string"})
        unknown = set(c["错误原因代码"].dropna()) - set(ERROR_CODES)
        if unknown:
            raise SystemExit(f"误判漏判清单_已归因.csv 用了代码表以外的代码：{unknown}")
        summary = c.groupby(["error", "错误原因代码"]).size().rename("n").reset_index()
        summary.to_csv(PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v0.2_error_codes.csv", index=False, encoding="utf-8-sig")
        print("ERROR_CODES", summary.to_dict("records"))
    print(f"METRICS -> {out}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
