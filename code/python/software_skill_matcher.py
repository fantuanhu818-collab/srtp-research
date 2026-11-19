"""一般软件技能词典匹配器。

匹配器读取 ``config/software_skill_rules_v0.1.csv``，并复用AI v1.0词典中的
分句、公司介绍和否定表达口径。它只负责单条广告的确定性规则识别，不读写数据文件。
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = PROJECT_ROOT / "config" / "software_skill_rules_v0.1.csv"
REPO_AI_DICTIONARY = PROJECT_ROOT / "config" / "ai_skill_dictionary_v1.0.json"
EXTERNAL_AI_DICTIONARY = Path(
    r"D:\SRTP中期\AI鎶€鑳借瘝鍏竉v1.0\ai_skill_dictionary_v1.0.json"
)
DEFAULT_AI_DICTIONARY = (
    REPO_AI_DICTIONARY if REPO_AI_DICTIONARY.exists() else EXTERNAL_AI_DICTIONARY
)

EMPTY_VALUES = {"", "nan", "none", "null", "-", "--", "—"}
WATERMARK_PATTERN = re.compile(
    r"(?:www\.)?macrodatas\.cn|马[\s-]*克[\s-]*(?:数[\s-]*据[\s-]*网|团[\s-]*队)|"
    r"来源[:：]?\s*马[\s-]*克[\s-]*数据网",
    flags=re.IGNORECASE,
)
EVIDENCE_CHARS = 500


def prepare_description(value: object) -> tuple[str, bool]:
    if value is None:
        return "", False
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if text.casefold() in EMPTY_VALUES:
        return "", False
    text = WATERMARK_PATTERN.sub(" ", text)
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r" +", " ", text).strip()
    visible = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text, len(visible) >= 10


class SoftwareSkillMatcher:
    def __init__(
        self,
        rule_path: Path | str = DEFAULT_RULES,
        ai_dictionary_path: Path | str = DEFAULT_AI_DICTIONARY,
    ) -> None:
        self.rule_path = Path(rule_path)
        self.ai_dictionary_path = Path(ai_dictionary_path)
        with self.rule_path.open("r", encoding="utf-8-sig", newline="") as handle:
            self.rules = list(csv.DictReader(handle))
        if not self.rules:
            raise ValueError("软件技能规则表为空")

        seen: set[str] = set()
        conditional_roots = {
            "SWC001": ("编程", "程序设计"),
            "SWC002": ("软件开发",),
            "SWC003": ("数据库",),
            "SWC004": ("数据可视化", "统计软件", "统计分析软件"),
            "SWC005": ("工程设计", "制图", "建模", "仿真"),
            "SWC006": ("erp", "crm"),
            "SWC007": ("办公软件", "office办公套件", "办公自动化软件"),
        }
        for rule in self.rules:
            rule_id = rule["rule_id"]
            if rule_id in seen:
                raise ValueError(f"软件技能规则ID重复: {rule_id}")
            seen.add(rule_id)
            rule["_exclude_regex"] = (
                re.compile(rule["exclude_pattern"], flags=re.IGNORECASE)
                if rule["exclude_pattern"]
                else None
            )
            rule["_regex"] = re.compile(rule["pattern"], flags=re.IGNORECASE)
            needles = {
                re.sub(r"\s+", "", alias).casefold()
                for alias in rule["aliases"].split(";")
                if len(re.sub(r"\s+", "", alias)) > 1
            }
            needles.update(conditional_roots.get(rule_id, ()))
            rule["_prefilter_needles"] = tuple(sorted(needles, key=len, reverse=True))
            rule["_single_r"] = rule_id == "SWA008"

        self.rule_lookup = {rule["rule_id"]: rule for rule in self.rules}
        self.single_r = re.compile(r"(?<![A-Za-z0-9_])R(?![A-Za-z0-9_])", re.IGNORECASE)

        ai_spec = json.loads(self.ai_dictionary_path.read_text(encoding="utf-8"))
        self.ai_rule_version = str(ai_spec["rule_version"])
        matching = ai_spec["matching"]
        self.split = re.compile(matching["clause_split_regex"])
        self.neg_prefix = (
            re.compile(matching["negation_prefix"], flags=re.IGNORECASE)
            if matching.get("negation_prefix")
            else None
        )
        self.neg_suffix = (
            re.compile(matching["negation_suffix"], flags=re.IGNORECASE)
            if matching.get("negation_suffix")
            else None
        )
        context = ai_spec["context"]
        bracket = r"^\s*[【\[<《]?\s*"
        self.intro_header = re.compile(bracket + f"(?:{context['intro_section_headers']})")
        self.req_header = re.compile(bracket + f"(?:{context['requirement_section_headers']})")
        self.strong_intro = re.compile(context["strong_intro_cues"])
        self.weak_intro = re.compile(context["weak_intro_cues"])
        self.req_cue = re.compile(context["requirement_cues"], flags=re.IGNORECASE)

    def clauses(self, text: str):
        section = "neutral"
        for part in self.split.split(text):
            clause = part.strip()
            if not clause:
                continue
            if self.req_header.search(clause):
                section = "requirement"
            elif self.intro_header.search(clause):
                section = "intro"
            yield clause, section

    def is_intro(self, clause: str, section: str) -> bool:
        has_requirement_cue = bool(self.req_cue.search(clause))
        if section == "intro":
            return True
        if self.strong_intro.search(clause):
            return section != "requirement" or not has_requirement_cue
        return bool(self.weak_intro.search(clause)) and not has_requirement_cue

    def _negated(self, clause: str, match: re.Match[str]) -> bool:
        if self.neg_prefix and self.neg_prefix.search(clause[: match.start()]):
            return True
        return bool(self.neg_suffix and self.neg_suffix.search(clause[match.end() :]))

    def _candidate_rules(self, text: str, *, title: bool) -> list[dict[str, str]]:
        compact = re.sub(r"\s+", "", text).casefold()
        candidates: list[dict[str, str]] = []
        for rule in self.rules:
            if title and rule["title_allowed"] != "1":
                continue
            if any(needle in compact for needle in rule["_prefilter_needles"]):
                candidates.append(rule)
            elif rule["_single_r"] and self.single_r.search(text):
                candidates.append(rule)
        return candidates

    def _valid_hits(
        self,
        text: str,
        candidate_rules: list[dict[str, str]],
        *,
        section: str = "requirement",
        title: bool = False,
    ) -> list[dict[str, str]]:
        if not text:
            return []
        hits: list[dict[str, str]] = []
        if not title and self.is_intro(text, section):
            return hits
        for rule in candidate_rules:
            exclude_regex = rule["_exclude_regex"]
            if exclude_regex and exclude_regex.search(text):
                continue
            match = next(
                (
                    match
                    for match in rule["_regex"].finditer(text)
                    if not self._negated(text, match)
                ),
                None,
            )
            if match:
                hits.append(
                    {
                        "rule_id": rule["rule_id"],
                        "subgroup": rule["software_subgroup"],
                        "term_level": rule["term_level"],
                        "match_text": match.group(0),
                        "evidence": (f"[标题]{text}" if title else text)[:EVIDENCE_CHARS],
                        "source": "title" if title else "description",
                    }
                )
        return hits

    def classify(self, title: object, description: object) -> dict[str, object]:
        title_text = (
            unicodedata.normalize("NFKC", title).strip() if isinstance(title, str) else ""
        )
        description_text, description_available = prepare_description(description)

        hits: list[dict[str, str]] = []
        if title_text:
            title_rules = self._candidate_rules(title_text, title=True)
            if title_rules:
                hits.extend(self._valid_hits(title_text, title_rules, title=True))
        if description_available:
            description_rules = self._candidate_rules(description_text, title=False)
        else:
            description_rules = []
        if description_rules:
            for clause, section in self.clauses(description_text):
                clause_rules = self._candidate_rules(clause, title=False)
                if clause_rules:
                    hits.extend(self._valid_hits(clause, clause_rules, section=section))

        unique_hits: list[dict[str, str]] = []
        seen_rules: set[str] = set()
        for hit in hits:
            if hit["rule_id"] in seen_rules:
                continue
            seen_rules.add(hit["rule_id"])
            unique_hits.append(hit)

        title_positive = any(hit["source"] == "title" for hit in unique_hits)
        text_available = bool(description_available or title_positive)
        value = None if not text_available else int(bool(unique_hits))
        subgroups = sorted({hit["subgroup"] for hit in unique_hits})
        levels = sorted({hit["term_level"] for hit in unique_hits})
        sources = sorted({hit["source"] for hit in unique_hits})
        office = any(hit["subgroup"] == "office_basic" for hit in unique_hits)
        professional = any(hit["subgroup"] != "office_basic" for hit in unique_hits)
        first = unique_hits[0] if unique_hits else None

        return {
            "skill_software": value,
            "skill_text_available": text_available,
            "software_rule_id": first["rule_id"] if first else "",
            "software_rule_ids": "|".join(hit["rule_id"] for hit in unique_hits),
            "software_subgroup": first["subgroup"] if first else "",
            "software_subgroups": "|".join(subgroups),
            "software_term_level": first["term_level"] if first else "",
            "software_term_levels": "|".join(levels),
            "software_match_text": first["match_text"] if first else "",
            "software_evidence": first["evidence"] if first else "",
            "software_match_source": first["source"] if first else "",
            "software_match_sources": "|".join(sources),
            "software_office_basic": None if value is None else int(office),
            "software_professional": None if value is None else int(professional),
            "software_has_conditional": None
            if value is None
            else int(any(hit["term_level"] == "conditional" for hit in unique_hits)),
            "software_title_hit": None
            if value is None
            else int(any(hit["source"] == "title" for hit in unique_hits)),
            "software_hit_count": len(unique_hits),
            "software_hits": unique_hits,
        }
