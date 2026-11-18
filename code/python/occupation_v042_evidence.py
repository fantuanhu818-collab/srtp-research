"""Occupation V4.2 候选证据分类器。

本模块只用于给 V4.1 的 Z99 补分类。它不会覆盖 V4.1 已经确定的职业代码，
也不会把“初级分类”单独当作决定依据。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULE_PATH = PROJECT_ROOT / "config" / "occupation_evidence_rules_v0.4.2.json"


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True)
class CompiledRule:
    occupation_id: str
    standard_name: str
    title_strong: tuple[re.Pattern, ...]
    title_decisive: tuple[re.Pattern, ...]
    title_exclude: tuple[re.Pattern, ...]
    description_strong: tuple[re.Pattern, ...]
    description_support: tuple[re.Pattern, ...]
    primary_patterns: tuple[re.Pattern, ...]


def _compile_many(patterns: list[str]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns)


class OccupationEvidenceClassifier:
    def __init__(self, path: Path = RULE_PATH) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.version = raw["version"]
        self.scoring = raw["scoring"]
        self.rules = tuple(
            CompiledRule(
                occupation_id=item["occupation_id"],
                standard_name=item["standard_name"],
                title_strong=_compile_many(item.get("title_strong", [])),
                title_decisive=_compile_many(item.get("title_decisive", [])),
                title_exclude=_compile_many(item.get("title_exclude", [])),
                description_strong=_compile_many(item.get("description_strong", [])),
                description_support=_compile_many(item.get("description_support", [])),
                primary_patterns=_compile_many(item.get("primary_patterns", [])),
            )
            for item in raw["rules"]
        )

    @staticmethod
    def _matched_patterns(patterns: tuple[re.Pattern, ...], text: str) -> list[str]:
        return [pattern.pattern for pattern in patterns if pattern.search(text)]

    def classify(
        self,
        title: object,
        description: object,
        primary_category: object,
        fuzzy_occupation_id: str = "",
        fuzzy_score: float = 0.0,
        fuzzy_margin: float = 0.0,
    ) -> dict:
        title_text = normalize_text(title)
        description_text = normalize_text(description)
        primary_text = normalize_text(primary_category)
        score_rows: list[dict] = []

        for rule in self.rules:
            title_excluded = bool(self._matched_patterns(rule.title_exclude, title_text))
            decisive_hits = [] if title_excluded else self._matched_patterns(rule.title_decisive, title_text)
            title_hits = [] if title_excluded else self._matched_patterns(rule.title_strong, title_text)
            strong_hits = self._matched_patterns(rule.description_strong, description_text)
            support_hits = self._matched_patterns(rule.description_support, description_text)
            primary_hits = self._matched_patterns(rule.primary_patterns, primary_text)

            score = 0
            if decisive_hits:
                score += int(self.scoring["title_decisive"])
            elif title_hits:
                score += int(self.scoring["title_strong"])
            score += min(
                len(strong_hits), int(self.scoring["maximum_strong_description_matches"])
            ) * int(self.scoring["description_strong"])
            score += min(
                len(support_hits), int(self.scoring["maximum_support_description_matches"])
            ) * int(self.scoring["description_support"])
            if primary_hits:
                score += int(self.scoring["primary_agreement"])
            fuzzy_agreement = (
                fuzzy_occupation_id == rule.occupation_id
                and fuzzy_score >= float(self.scoring["fuzzy_name_minimum_score"])
            )
            if fuzzy_agreement:
                score += int(self.scoring["fuzzy_name_agreement"])

            if score:
                score_rows.append({
                    "occupation_id": rule.occupation_id,
                    "standard_name": rule.standard_name,
                    "score": score,
                    "title_hits": title_hits,
                    "decisive_hits": decisive_hits,
                    "strong_hits": strong_hits,
                    "support_hits": support_hits,
                    "primary_hits": primary_hits,
                    "fuzzy_agreement": fuzzy_agreement,
                })

        score_rows.sort(key=lambda item: (-item["score"], item["occupation_id"]))
        if not score_rows:
            return self._empty_result("no_evidence")

        top = score_rows[0]
        second_score = score_rows[1]["score"] if len(score_rows) > 1 else 0
        margin = top["score"] - second_score
        independent_description = len(top["strong_hits"])
        has_required_evidence = (
            bool(top["decisive_hits"])
            or bool(top["title_hits"])
            or independent_description >= 2
            or (top["fuzzy_agreement"] and independent_description >= 1)
        )
        accepted = (
            top["score"] >= int(self.scoring["minimum_score"])
            and margin >= int(self.scoring["minimum_margin"])
            and has_required_evidence
        )

        if not accepted:
            if not has_required_evidence:
                status = "insufficient_independent_evidence"
            elif top["score"] < int(self.scoring["minimum_score"]):
                status = "score_below_threshold"
            else:
                status = "evidence_conflict_small_margin"
            return {
                **self._empty_result(status),
                "candidate_occupation_id": top["occupation_id"],
                "candidate_standard_name": top["standard_name"],
                "score_top1": top["score"],
                "score_top2": second_score,
                "score_margin": margin,
                "title_evidence": "；".join(top["decisive_hits"] or top["title_hits"]),
                "description_strong_evidence": "；".join(top["strong_hits"]),
                "description_support_evidence": "；".join(top["support_hits"]),
                "primary_evidence": "；".join(top["primary_hits"]),
                "fuzzy_evidence": (
                    f"{fuzzy_occupation_id};score={fuzzy_score:.1f};margin={fuzzy_margin:.1f}"
                    if top["fuzzy_agreement"] else ""
                ),
            }

        if top["decisive_hits"] and (top["strong_hits"] or top["support_hits"]):
            method = "decisive_title_and_description"
        elif top["decisive_hits"]:
            method = "decisive_title_rule"
        elif top["fuzzy_agreement"] and top["strong_hits"]:
            method = "fuzzy_name_and_description_evidence"
        elif top["title_hits"] and (top["strong_hits"] or top["support_hits"]):
            method = "title_and_description_evidence"
        elif top["title_hits"] and top["primary_hits"]:
            method = "title_and_primary_confirmation"
        elif top["title_hits"]:
            method = "title_multi_evidence"
        else:
            method = "description_multi_evidence"
        confidence = "high" if (
            (top["title_hits"] and top["strong_hits"])
            or (top["score"] >= 7 and margin >= 3)
        ) else "medium"
        return {
            "accepted": True,
            "status": "v042_evidence_accepted",
            "candidate_occupation_id": top["occupation_id"],
            "candidate_standard_name": top["standard_name"],
            "method": method,
            "confidence": confidence,
            "score_top1": top["score"],
            "score_top2": second_score,
            "score_margin": margin,
            "title_evidence": "；".join(top["decisive_hits"] or top["title_hits"]),
            "description_strong_evidence": "；".join(top["strong_hits"]),
            "description_support_evidence": "；".join(top["support_hits"]),
            "primary_evidence": "；".join(top["primary_hits"]),
            "fuzzy_evidence": (
                f"{fuzzy_occupation_id};score={fuzzy_score:.1f};margin={fuzzy_margin:.1f}"
                if top["fuzzy_agreement"] else ""
            ),
        }

    @staticmethod
    def _empty_result(status: str) -> dict:
        return {
            "accepted": False,
            "status": status,
            "candidate_occupation_id": "Z99",
            "candidate_standard_name": "",
            "method": "v042_evidence_not_accepted",
            "confidence": "unclassified",
            "score_top1": 0,
            "score_top2": 0,
            "score_margin": 0,
            "title_evidence": "",
            "description_strong_evidence": "",
            "description_support_evidence": "",
            "primary_evidence": "",
            "fuzzy_evidence": "",
        }

