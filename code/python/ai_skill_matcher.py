"""AI技能识别规则（可被其他程序导入）。

读取 config/ai_skill_dictionary_*.json，对一条招聘广告的“招聘岗位”和“职位描述”判断：

- ai_skill：严格词出现在非公司介绍句中 → 1；
- ai_skill_broad：ai_skill=1，或宽泛词出现在带岗位要求/职责线索的句子中 → 1；
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
            Term(t["id"], _term_regex(t, ignore_case), t["category"], t["tier"]) for t in spec["terms"]
        ]
        known = {t.id for t in self.terms}
        self.exclusions: dict[str, list[re.Pattern]] = {}
        for ex in spec["term_exclusions"]:
            for term_id in ex["terms"]:
                if term_id not in known:
                    raise ValueError(f"排除规则引用了不存在的词条：{term_id}")
                self.exclusions.setdefault(term_id, []).append(re.compile(ex["clause_pattern"]))
        # 快速预筛：绝大多数广告不含任何AI词，直接返回0。
        self.prefilter = re.compile("|".join(f"(?:{t['pattern']})" for t in spec["terms"]), re.IGNORECASE)
        self.split = re.compile(spec["matching"]["clause_split_regex"])
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

    def _hits(self, clause: str) -> list[Term]:
        found = []
        for term in self.terms:
            if term.regex.search(clause) and not any(p.search(clause) for p in self.exclusions.get(term.id, [])):
                found.append(term)
        return found

    # ---------- 单条广告 ----------
    def classify(self, title: object, description: object) -> dict:
        title = title.strip() if isinstance(title, str) else ""
        desc = description.strip() if isinstance(description, str) else ""
        strict: dict[str, Term] = {}
        broad: dict[str, Term] = {}
        review = False
        intro_hit = False
        evidence = ""

        def record(term: Term, clause: str) -> None:
            nonlocal evidence
            (strict if term.tier == "strict" else broad)[term.id] = term
            if not evidence:
                evidence = clause[:EVIDENCE_CHARS]

        # 标题：本身就是岗位，不做公司介绍判断。
        if title and self.prefilter.search(title):
            for term in self._hits(title):
                if term.tier == "review":
                    review = True
                else:
                    record(term, f"[标题]{title}")

        if desc and self.prefilter.search(desc):
            for clause, section in self.clauses(desc):
                hits = self._hits(clause)
                if not hits:
                    continue
                intro = self.is_intro(clause, section)
                requirement = section == "requirement" or bool(self.req_cue.search(clause))
                for term in hits:
                    if term.tier == "review":
                        review = True
                    elif intro:
                        intro_hit = True
                    elif term.tier == "strict" or requirement:
                        record(term, clause)

        if not desc and not strict and not broad:
            ai_skill = ai_broad = None
        else:
            ai_skill = int(bool(strict))
            ai_broad = int(bool(strict) or bool(broad))
        return {
            "ai_skill": ai_skill,
            "ai_skill_broad": ai_broad,
            "ai_genai": None if ai_skill is None else int(any(t.category == "generative" for t in strict.values())),
            "ai_traditional": None if ai_skill is None else int(any(t.category == "traditional" for t in strict.values())),
            "ai_strict_terms": "|".join(sorted(strict)),
            "ai_broad_terms": "|".join(sorted(broad)),
            "ai_intro_only": int(intro_hit and not strict and not broad),
            "ai_review_flag": int(review),
            "ai_evidence": evidence,
        }
