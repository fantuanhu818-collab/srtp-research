"""AI技能识别规则（可被其他程序导入）。

读取 config/ai_skill_dictionary_*.json，对一条招聘广告的“招聘岗位”和“职位描述”判断：

- ai_skill：严格词出现在非公司介绍句中 → 1；
  条件词（v0.2新增层级）出现在非公司介绍句中，且广告里还有另一个不同的严格词或条件词 → 1；
- ai_skill_broad：ai_skill=1，或宽泛词出现在带岗位要求/职责线索的句子中，或有没搭配上的条件词 → 1；
- v0.2词典另输出 ai_skill_2cat、ai_intensity、ai_conditional_terms（v0.1词典没有条件词和分组，结果与原来一致）；
- 职位描述缺失且标题无命中 → None（不得自动编码为0）。

规则说明见 docs/AI技能识别方案与人工标注规则_v0.1.md。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DICTIONARY = Path(__file__).resolve().parents[2] / "config" / "ai_skill_dictionary_v0.1.json"
EVIDENCE_CHARS = 120


@dataclass(frozen=True)
class Term:
    id: str
    regex: re.Pattern
    category: str
    tier: str
    group: str | None = None
    relevance: float | None = None


def _term_regex(spec: dict, default_ignore_case: bool) -> re.Pattern:
    pattern = f"(?:{spec['pattern']})"
    if spec.get("word"):
        pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
    ignore_case = default_ignore_case and not spec.get("case_sensitive", False)
    return re.compile(pattern, re.IGNORECASE if ignore_case else 0)


class AISkillMatcher:
    def __init__(self, dictionary_path: Path | str = DEFAULT_DICTIONARY) -> None:
        spec = json.loads(Path(dictionary_path).read_text(encoding="utf-8"))
        self.rule_version: str = spec["rule_version"]
        ignore_case = spec["matching"]["case_insensitive_default"]
        self.terms = [
            Term(t["id"], _term_regex(t, ignore_case), t["category"], t["tier"], t.get("group"), t.get("relevance_v02"))
            for t in spec["terms"]
        ]
        known = {t.id for t in self.terms}
        self.exclusions: dict[str, list[re.Pattern]] = {}
        for ex in spec["term_exclusions"]:
            for term_id in ex["terms"]:
                if term_id not in known:
                    raise ValueError(f"排除规则引用了不存在的词条：{term_id}")
                flags = re.IGNORECASE if spec["matching"].get("exclusion_case_insensitive") else 0
                self.exclusions.setdefault(term_id, []).append(re.compile(ex["clause_pattern"], flags))
        # 快速预筛：绝大多数广告不含任何AI词，直接返回0。
        self.prefilter = re.compile("|".join(f"(?:{t['pattern']})" for t in spec["terms"]), re.IGNORECASE)
        self.split = re.compile(spec["matching"]["clause_split_regex"])
        # 否定表达（11-19与A的非AI技能口径对齐）：同一句中，匹配前紧挨着“无需/不要求”等，
        # 或匹配后紧跟“不限/不作要求”等，该处不计。“者优先”不受影响。旧词典没有这两项，结果不变。
        neg = spec["matching"]
        self.neg_prefix = re.compile(neg["negation_prefix"]) if neg.get("negation_prefix") else None
        self.neg_suffix = re.compile(neg["negation_suffix"]) if neg.get("negation_suffix") else None
        # 岗位名称是否能单独决定 ai_skill（A的口径：岗位名称不决定技能变量）。默认沿用旧行为。
        self.title_counts_strict: bool = neg.get("title_counts_strict", True)
        ctx = spec["context"]
        bracket = r"^\s*[【\[<《]?\s*"
        self.intro_header = re.compile(bracket + f"(?:{ctx['intro_section_headers']})")
        self.req_header = re.compile(bracket + f"(?:{ctx['requirement_section_headers']})")
        self.strong_intro = re.compile(ctx["strong_intro_cues"])
        self.weak_intro = re.compile(ctx["weak_intro_cues"])
        self.req_cue = re.compile(ctx["requirement_cues"], re.IGNORECASE)

    # ---------- 句子与段落 ----------
    def clauses(self, text: str):
        """按句切分，并跟踪当前处于公司介绍段、岗位要求段还是未知段。"""
        section = "neutral"
        for part in self.split.split(text):
            part = part.strip()
            if not part:
                continue
            if self.req_header.search(part):
                section = "requirement"
            elif self.intro_header.search(part):
                section = "intro"
            yield part, section

    def is_intro(self, clause: str, section: str) -> bool:
        has_req = bool(self.req_cue.search(clause))
        if section == "intro":
            return True
        if self.strong_intro.search(clause):
            return section != "requirement" or not has_req
        return bool(self.weak_intro.search(clause)) and not has_req

    def _negated(self, clause: str, m: re.Match) -> bool:
        if self.neg_prefix and self.neg_prefix.search(clause[:m.start()]):
            return True
        return bool(self.neg_suffix and self.neg_suffix.search(clause[m.end():]))

    def _hits(self, clause: str) -> list[tuple[Term, str]]:
        found = []
        for term in self.terms:
            if any(p.search(clause) for p in self.exclusions.get(term.id, [])):
                continue
            # 取第一处没有被否定的匹配
            m = next((m for m in term.regex.finditer(clause) if not self._negated(clause, m)), None)
            if m:
                found.append((term, m.group(0)))
        return found

    # ---------- 单条广告 ----------
    def classify(self, title: object, description: object) -> dict:
        title = title.strip() if isinstance(title, str) else ""
        desc = description.strip() if isinstance(description, str) else ""
        found: dict[str, dict[str, Term]] = {"strict": {}, "conditional": {}, "broad": {}}
        review = False
        intro_hit = False
        evidence = {"strict": "", "conditional": "", "broad": ""}

        cond_texts: set[str] = set()  # 条件词实际匹配到的文字（去空格、小写）

        def record(term: Term, clause: str, text: str) -> None:
            found[term.tier][term.id] = term
            if term.tier == "conditional":
                cond_texts.add(re.sub(r"[\s_-]+", "", text).lower())
            if not evidence[term.tier]:
                evidence[term.tier] = clause[:EVIDENCE_CHARS]

        # 标题：本身就是岗位，不做公司介绍判断。
        # title_counts_strict=False 时，标题里的严格词、条件词只记为宽泛（标题不能单独决定 ai_skill）。
        title_terms: list[tuple[Term, str]] = []
        if title and self.prefilter.search(title):
            for term, text in self._hits(title):
                if term.tier == "review":
                    review = True
                elif self.title_counts_strict:
                    record(term, f"[标题]{title}", text)
                else:
                    title_terms.append((term, text))

        if desc and self.prefilter.search(desc):
            for clause, section in self.clauses(desc):
                hits = self._hits(clause)
                if not hits:
                    continue
                intro = self.is_intro(clause, section)
                requirement = section == "requirement" or bool(self.req_cue.search(clause))
                for term, text in hits:
                    if term.tier == "review":
                        review = True
                    elif intro:
                        intro_hit = True
                    elif term.tier in ("strict", "conditional") or requirement:
                        record(term, clause, text)

        for term, _ in title_terms:
            found["broad"].setdefault(term.id, term)
            if not evidence["broad"]:
                evidence["broad"] = f"[标题]{title}"[:EVIDENCE_CHARS]

        strict, cond, broad = found["strict"], found["conditional"], found["broad"]
        # 条件词：有严格词，或至少两个不同的条件词时才计入；否则只算宽泛。
        # “不同”按匹配到的文字算：同一处文字被几个写法相近的词同时匹配（如LDA、VisionPro/Cognex VisionPro），只算一个。
        distinct = {t for t in cond_texts if not any(t != u and t in u for u in cond_texts)}
        if strict or len(distinct) >= 2:
            strict = {**strict, **cond}
            unpaired: dict[str, Term] = {}
        else:
            unpaired = cond
            if cond and not evidence["broad"]:
                evidence["broad"] = evidence["conditional"]
        if not strict:
            evidence["strict"] = ""
        elif not evidence["strict"]:
            evidence["strict"] = evidence["conditional"]

        # v1为确定性规则，不产生 uncertain；该状态留给以后的模型方法。
        if not desc and not strict and not broad and not unpaired:
            ai_skill = ai_broad = None
            status = "text_missing"
        else:
            ai_skill = int(bool(strict))
            ai_broad = int(bool(strict) or bool(broad) or bool(unpaired))
            status = "positive" if ai_skill else "negative"
        groups = {t.group for t in found["strict"].values() if t.group}
        rels = [t.relevance for t in strict.values() if t.relevance is not None]
        return {
            "ai_skill": ai_skill,
            "ai_status": status,
            "ai_skill_broad": ai_broad,
            "ai_genai": None if ai_skill is None else int(any(t.category == "generative" for t in strict.values())),
            "ai_traditional": None if ai_skill is None else int(any(t.category == "traditional" for t in strict.values())),
            "ai_hit_terms": "|".join(sorted(strict)),
            "ai_broad_terms": "|".join(sorted(broad)),
            "ai_conditional_terms": "|".join(sorted(unpaired)),
            # 至少两类：命中的严格层级词来自两个不同的种子组（条件词不计）
            "ai_skill_2cat": None if ai_skill is None else int(len(groups) >= 2),
            # AI强度：计入 ai_skill 的词的相关度平均值；未命中为0；命中词都没有相关度时为空
            "ai_intensity": None if ai_skill is None else (0.0 if not strict else
                                                          (round(sum(rels) / len(rels), 4) if rels else None)),
            "ai_intro_only": int(intro_hit and not strict and not broad and not unpaired),
            "ai_review_flag": int(review),
            # 证据优先展示决定 ai_skill 的严格词所在句
            "ai_evidence": evidence["strict"] or evidence["broad"],
        }
