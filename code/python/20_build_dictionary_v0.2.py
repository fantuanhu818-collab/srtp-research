"""规则v0.2第5步：由v0.1.1词典生成v0.2词典（方案第4.2节、第6.1节）。

改动（都写进词典的 changelog_v0.2 和各词条的 note_v0.2）：
  1. 层级只降不升：相关度<30%（或出现不足30条）的严格词降为条件词；宽泛词全部保持宽泛。
  2. 例外：单独出现的“大模型”（b_llm_bare）升为严格词，加窄排除规则。
  3. 7条已知误判的窄排除规则。
  4. 每个严格词/条件词记录所属种子组（group，供 ai_skill_2cat）和相关度（relevance_v02，供 ai_intensity）。
  5. 可选：--screening 给出第4步合并结果时，加入两人都同意的新词（source = w2v_expansion）。

输入：config/ai_skill_dictionary_v0.1.json、outputs/qc/ai_term_relevance_v0.2.csv、
     outputs/qc/ai_w2v_candidates_v0.2.csv（新词的相关度）、[可选] 第4步合并结果
输出：config/ai_skill_dictionary_v0.2_draft.json（无广告原文）
     docs/AI技能词典_v0.2_词表.md（给人看的词表：每个词的写法、层级、相关度、改动说明和排除规则）

运行：.venv/bin/python code/python/20_build_dictionary_v0.2.py [--screening outputs/qc/ai_w2v_screening_v0.2_merged.csv]
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "config"
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
SRC = CONFIG / "ai_skill_dictionary_v0.1.json"
OUT = CONFIG / "ai_skill_dictionary_v0.2_draft.json"
READABLE = PROJECT_ROOT / "docs" / "AI技能词典_v0.2_词表.md"
TIER_ZH = {"strict": "严格", "conditional": "条件", "broad": "宽泛", "review": "待审"}
CAT_ZH = {"traditional": "传统AI", "generative": "生成式AI", "unspecified": "未区分"}
SRC_ZH = {"AAHR2022_narrow": "Acemoglu等清单", "AAHR2022_broad_cluster": "Acemoglu等宽口径", "project_extension": "项目补充",
          "project_genai": "项目补充（生成式）", "w2v_expansion": "Word2Vec新增"}
RULE_VERSION = "ai_skill_dict_v0.2_draft_2026-11-17"
GROUPS = importlib.import_module("16_w2v_candidates").GROUPS
TIER_CODE = {"strict": "strict", "conditional": "conditional", "broad": "broad"}

# 第6.1节：窄排除规则。clause_pattern 在同一句内匹配到即不计该词（不区分大小写）。
NEW_EXCLUSIONS = [
    {"terms": ["b_llm_bare"],
     "clause_pattern": r"大模型\d?(?:展示|渲染|加载|数据轻量化)|(?:城市|BIM|三维|3D|倾斜摄影|实景)\S{0,3}大模型",
     "note": "v0.2：单独“大模型”升为严格词；三维模型用法（Web端大模型展示、大模型数据轻量化、城市大模型、BIM大模型等）不算。"
             "11-18全样本核对后收窄：不再因同句出现“3D”“三维”“特效”或“大模型建模/轻量化”就排除"
             "（误伤“自然语言大模型建模工程师”“大模型轻量化部署”“视觉大模型、3D视觉”）。“场景”“平台”太宽泛，不进排除规则"},
    {"terms": ["g_llm_en"],
     "clause_pattern": r"法学|法律|律师|Master of Laws",
     "note": "v0.2误判1：LLM指法学硕士（Master of Laws）"},
    {"terms": ["g_prompt_eng"],
     "clause_pattern": r"(?:搜索|输入)提示词",
     "note": "v0.2误判2：“搜索提示词”“输入提示词”是搜索框文字"},
    {"terms": ["g_image_gen_tools"],
     "clause_pattern": r"(?<![A-Za-z])(?:PS|Photoshop|CDR|CorelDRAW)\s*[/、，,]\s*AI(?:绘图|绘画|作图)",
     "note": "v0.2误判3：“PS/AI绘图”中的AI指Adobe Illustrator（原设计软件排除规则未覆盖g_image_gen_tools）"},
    {"terms": ["g_finetune"],
     "clause_pattern": r"^(?!.*(?:大模型|LLM|语言模型|GPT|AIGC|深度学习|神经网络)).*(?:3D|三维|建模|动画|角色|贴图)",
     "note": "v0.2误判4：3D建模、动画岗位里的“模型微调”；同句有大模型/LLM等词时不排除"},
    {"terms": ["g_finetune"],
     "clause_pattern": r"^(?!.*(?:model|模型|LLM|GPT|BERT|(?<![a-z])AI(?![a-z])|神经网络|深度学习|transformer|LoRA|SFT|RLHF|微调|精调"
                       r"|训练|量化|剪枝|蒸馏|推理|算法|PyTorch|TensorFlow|芯片|NPU)).*fine-?tun",
     "note": "v0.2误判5：非AI语境的英文fine-tune（如生产线setup、fine-tuning）；同句有model、LLM、训练、量化、剪枝、蒸馏、算法等词时不排除"
             "（11-18全样本核对后补充，避免误伤“针对海思芯片finetune”“fine-tune、剪枝、蒸馏”）"},
    {"terms": ["g_agent"],
     "clause_pattern": r"(?:城市|园区)智能体",
     "note": "v0.2误判6：“城市智能体”“园区智能体”是智慧城市产品名"},
    {"terms": ["g_gpt"],
     "clause_pattern": r"GPT\s*会议",
     "note": "v0.2误判7：“GPT会议”不是技能写法"},
]


# 11-18全样本核对（23_check_new_terms.py）：短中文词嵌在别的词里被多匹配，改用更窄的写法
PATTERN_OVERRIDES = {
    "训推": r"(?<!培)训推",          # 培训推广
    "可灵": r"可灵(?!活)",           # 可灵活
    "光流": r"(?<![抛布验荧心])光流(?![程式美])",  # 抛光流程、验光流程、荧光流式、心光流美
    "超分": r"超分(?![支公析院])",     # 超分支机构、超分公司、节超分析
    "配准": r"(?<![分调])配准",       # 分配准确、调配准确
    "降维": r"降维(?!修)",           # 节降维修
    "问财": r"(?<!顾)问财",          # 理财顾问财富
    "精调": r"(?<!香)精调",          # 香精调香
}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def new_term(cand: str, group: str, tier: str, relevance: float | None) -> dict:
    """第4步新词 → 词条。英文用整词匹配；Phrases合并的下划线还原为可选空格。"""
    ascii_ = bool(re.fullmatch(r"[\x00-\x7f]+", cand))
    pattern = PATTERN_OVERRIDES.get(cand) or re.escape(cand).replace("_", r"[ _-]?")
    category = "generative" if group == "生成式AI" else "traditional"
    tid = "w_" + re.sub(r"[^0-9a-zA-Z]+", "_", cand).strip("_").lower() if ascii_ else "w_" + cand
    return {"id": tid, "pattern": pattern, "category": category, "tier": tier, "word": ascii_,
            "source": "w2v_expansion", "group": group,
            "relevance_v02": relevance}


def md_cell(x: object) -> str:
    return "" if x is None else str(x).replace("|", "\\|").replace("\n", " ")


def write_readable(spec: dict) -> None:
    lines = [f"# AI技能识别词典（{spec['rule_version']}）", "",
             "本文件由 `code/python/20_build_dictionary_v0.2.py` 自动生成，不要手改；程序读取的是 "
             "`config/ai_skill_dictionary_v0.2_draft.json`。", "",
             "## 层级含义", ""]
    lines += [f"- **{TIER_ZH[k]}**：{v}" for k, v in spec["tiers"].items()]
    lines += ["", "“写法”是正则表达式：`|` 表示“或”，`(?:…)` 是分组，`(?<!…)`、`(?!…)` 表示前后不能紧挨某些字。", ""]
    order = ["strict", "conditional", "broad", "review"]
    for tier in order:
        terms = [t for t in spec["terms"] if t["tier"] == tier]
        lines += [f"## {TIER_ZH[tier]}词（{len(terms)}个）", "",
                  "|编号|写法|类别|种子组|相关度|来源|v0.2改动|", "|---|---|---|---|---:|---|---|"]
        for t in sorted(terms, key=lambda t: (t.get("group") or "", t["id"])):
            rel = t.get("relevance_v02")
            lines.append("|" + "|".join(md_cell(x) for x in [
                t["id"], f"`{t['pattern']}`", CAT_ZH.get(t["category"], t["category"]), t.get("group"),
                "" if rel is None else f"{rel:.1%}", SRC_ZH.get(t.get("source"), t.get("source")),
                t.get("note_v0.2", "")]) + "|")
        lines.append("")
    lines += ["## 排除规则", "", "同一句里匹配到“排除条件”时，这一句不计该词（不区分大小写）。", "",
              "|#|适用词条|排除条件|说明|", "|---|---|---|---|"]
    for i, e in enumerate(spec["term_exclusions"], 1):
        lines.append("|" + "|".join(md_cell(x) for x in [i, "、".join(e["terms"]), f"`{e['clause_pattern']}`", e["note"]]) + "|")
    lines += ["", "## v0.2改动记录", ""] + [f"- {c}" for c in spec["changelog_v0.2"]] + [""]
    READABLE.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screening", type=Path, help="第4步合并结果（19_merge_screening.py 输出的 QC 版）")
    args = ap.parse_args()

    spec = json.loads(SRC.read_text(encoding="utf-8"))
    rel = {r["term_id"]: r for r in read_csv(QC_DIR / "ai_term_relevance_v0.2.csv")}
    group_of = {tid: g for g, ids in GROUPS.items() for tid in ids}
    changelog = []

    for t in spec["terms"]:
        r = rel[t["id"]]
        t["relevance_v02"] = None if r["relevance"] == "" else float(r["relevance"])
        if t["id"] in group_of:
            t["group"] = group_of[t["id"]]
        change = r["tier_change"]
        if change.startswith("strict→conditional"):
            t["tier"] = "conditional"
            why = "出现不足30条，默认条件词" if int(r["n_basis"]) < 30 else f"相关度{float(r['relevance']):.1%}<30%"
            t["note_v0.2"] = f"严格词→条件词：{why}"
            changelog.append(f"{t['id']}: strict→conditional（{why}）")
        elif change.startswith("broad→") and t["id"] != "b_llm_bare":
            t["note_v0.2"] = (f"相关度{float(r['relevance']):.1%}达到{change.split('→')[1]}门槛，但按“只降级不升级”保持宽泛词："
                              "相关度在全部含该词的广告上计算，不描述该词单独出现的广告")
            changelog.append(f"{t['id']}: 保持broad（门槛建议{change}，不执行）")
    bare = next(t for t in spec["terms"] if t["id"] == "b_llm_bare")
    bare.update(tier="strict", group="生成式AI",
                **{"note_v0.2": "宽泛词→严格词（唯一的升级例外）：ChatGPT后单独出现基本指大语言模型；三维模型用法由排除规则去掉；不按年份划分词义"})
    changelog.append("b_llm_bare: broad→strict（例外），加三维模型排除规则")

    spec["term_exclusions"].extend(NEW_EXCLUSIONS)
    changelog += [f"排除规则：{e['note']}" for e in NEW_EXCLUSIONS]

    if args.screening:
        cands = {r["candidate"]: r for r in read_csv(QC_DIR / "ai_w2v_candidates_v0.2.csv")}
        known = {t["id"] for t in spec["terms"]}
        added = 0
        for r in read_csv(args.screening):
            if r["加入"] != "1":
                continue
            c = cands[r["候选词"]]
            term = new_term(r["候选词"], r["来源组"].split("|")[0], TIER_CODE[r["层级"]],
                            float(c["relevance"]) if c["relevance"] else None)
            if term["id"] in known:
                raise SystemExit(f"新词id重复：{term['id']}")
            known.add(term["id"])
            spec["terms"].append(term)
            added += 1
        changelog.append(f"加入第4步筛选通过的新词{added}个（source = w2v_expansion）")
        # 新词“微调”“精调”也适用3D/动画“模型微调”的排除规则（误判4）
        rule4 = next(e for e in spec["term_exclusions"] if e["note"].startswith("v0.2误判4"))
        inherit = [i for i in ("w_微调", "w_精调") if i in known]
        if inherit:
            rule4["terms"] = rule4["terms"] + inherit
            changelog.append(f"误判4排除规则同时用于新词{'、'.join(inherit)}")

    spec["rule_version"] = RULE_VERSION
    spec["status"] = "draft: v0.2草稿，待全样本核对排除规则和第6步人工标注"
    spec["tiers"]["conditional"] = ("v0.2新增。出现在非公司介绍句中，且同一广告还有另一个不同的严格词或条件词时才计入 ai_skill；"
                                    "否则只记入 ai_conditional_terms 和 ai_skill_broad。")
    spec["changelog_v0.2"] = changelog
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_readable(spec)
    for line in changelog:
        print(line)
    print(f"WROTE {OUT.relative_to(PROJECT_ROOT)} terms={len(spec['terms'])} exclusions={len(spec['term_exclusions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
