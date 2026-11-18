"""V4职业类型分类器。

V4保留37个职业组，重点修正岗位名称标准化、歧义短语、人工确认别名、
高分模糊匹配和“标准职业名称 -> 37组代码”的两阶段衔接。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
OVERRIDE_PATH = PROJECT_ROOT / "config" / "occupation_rule_overrides_v0.4.json"
ANCHOR_PATH = PROJECT_ROOT / "config" / "occupation_name_dictionary_v0.3.csv"
MANUAL_GOLD_PATH = PROJECT_ROOT / "config" / "occupation_manual_gold_v0.4.csv"
MANUAL_ADJUDICATION_PATH = PROJECT_ROOT / "config" / "occupation_manual_adjudication_v0.4.csv"
VERSION = "occupation_v0.4.1_independent_validation_feedback_20261118"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_base_classifier():
    module_path = PROJECT_ROOT / "code" / "python" / "12_pilot_occupation_2022.py"
    spec = importlib.util.spec_from_file_location("occupation_v01_for_v04", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入v0.1职业分类器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = load_json(BASE_RULE_PATH)
    classifier, _ = module.build_classifier(config)
    return classifier, config


@lru_cache(maxsize=None)
def normalize_title_v04(value: str) -> str:
    """清理广告、公司、地点、职级和职位编号，同时保留职业核心词。"""
    text = unicodedata.normalize("NFKC", value or "").lower().strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)

    # 只删除明显属于公司、地点或编号的括号，保留“PTE(产品测试工程师)”等职业解释。
    removable_parenthetical = re.compile(
        r"\([^)]*(?:有限公司|股份公司|集团|科技公司|银行|医院|学校|工作地点|职位编号|岗位编号|编号|j\d{3,}|[省市区县]工作)[^)]*\)",
        flags=re.IGNORECASE,
    )
    previous = None
    while previous != text:
        previous = text
        text = removable_parenthetical.sub("", text)

    text = re.sub(r"\((?:j|职位|岗位)?\d{3,}[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|[-_/|])j\d{3,}(?:$|[-_/|])", "-", text, flags=re.IGNORECASE)
    text = re.sub(r"^\d{4}年?(?:春季|秋季)?(?:校园招聘|校招|社会招聘|社招)[-_:：]*", "", text)
    text = re.sub(r"^(?:春季|秋季)?(?:校园招聘|校招|社会招聘|社招)[-_:：]*", "", text)
    text = re.sub(r"^(?:急聘|诚聘|高薪急聘|高薪聘请|直招|热招)+[:：_-]*", "", text)
    text = re.sub(r"^(?:六险一金|五险一金|双休|周末双休|提供客源|包吃包住|带薪培训)[/+、_-]*", "", text)
    text = re.sub(r"(?:招聘)?\d+名?$", "", text)
    text = re.sub(r"(?:初中高级|中高级|初中级|初级|中级|高级|资深)", "", text)
    text = re.sub(r"\[(?:急聘|高薪|校招|社招|职位编号)[^]]*\]", "", text)
    text = re.sub(r"【(?:急聘|高薪|校招|社招|职位编号)[^】]*】", "", text)
    text = re.sub(r"[-_/|·,，;；:：]+", "-", text)
    return text.strip("-—_/|·,，;；:：()[]【】")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class OccupationV04Classifier:
    def __init__(self) -> None:
        self.base_classifier, self.base_config = load_base_classifier()
        self.override = load_json(OVERRIDE_PATH)
        self.occupation_names = self.base_config["occupation_names"]
        self.l1_names = self.base_config["l1_names"]
        self.fuzzy_threshold = float(self.override["fuzzy_threshold"])
        self.fuzzy_minimum_margin = float(self.override["fuzzy_minimum_margin"])
        self.fuzzy_minimum_length = int(self.override["fuzzy_minimum_length"])
        self.ambiguous_titles = {
            normalize_title_v04(value) for value in self.override["ambiguous_titles"]
        }
        self.context_rules = self._compile_context_rules(self.override["context_rules"])
        self.manual_aliases, self.manual_alias_audit = self._build_manual_aliases()
        self.anchor_lookup, self.fuzzy_candidates = self._build_anchor_lookup()

    @staticmethod
    def _compile_context_rules(raw_rules: list[dict]) -> list[dict]:
        compiled = []
        for order, raw in enumerate(raw_rules):
            rule = dict(raw)
            rule["order"] = order
            rule["priority"] = int(rule.get("priority", 100))
            rule["title_re"] = re.compile(rule["title_pattern"], flags=re.IGNORECASE)
            rule["description_re"] = (
                re.compile(rule["description_pattern"], flags=re.IGNORECASE)
                if rule.get("description_pattern") else None
            )
            rule["exclude_re"] = (
                re.compile(rule["exclude_pattern"], flags=re.IGNORECASE)
                if rule.get("exclude_pattern") else None
            )
            compiled.append(rule)
        return sorted(compiled, key=lambda item: (item["priority"], item["order"]))

    def _build_manual_aliases(self) -> tuple[dict[str, dict], list[dict]]:
        rows = _read_csv(MANUAL_GOLD_PATH)
        adjudication = {
            row["source_record_id"]: row["adjudication_status"]
            for row in _read_csv(MANUAL_ADJUDICATION_PATH)
        }
        for row in rows:
            if row["source_record_id"] in adjudication:
                row["manual_status"] = adjudication[row["source_record_id"]]
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            normalized = normalize_title_v04(row["job_title_raw"])
            if normalized:
                grouped[normalized].append(row)

        aliases: dict[str, dict] = {}
        audit: list[dict] = []
        for normalized, items in grouped.items():
            statuses = {row["manual_status"] for row in items}
            codes = {
                row["manual_final_occupation_id"]
                for row in items
                if row["manual_final_occupation_id"]
            }
            names = [
                row["manual_final_standard_name"]
                for row in items
                if row["manual_final_standard_name"]
            ]
            eligible = (
                statuses == {"confirmed"}
                and len(codes) == 1
                and normalized not in self.ambiguous_titles
            )
            reason = "accepted"
            if statuses != {"confirmed"}:
                reason = "pending_or_unresolved"
            elif len(codes) != 1:
                reason = "conflicting_codes"
            elif normalized in self.ambiguous_titles:
                reason = "ambiguous_title"
            if eligible:
                code = next(iter(codes))
                standard_name = Counter(names).most_common(1)[0][0]
                aliases[normalized] = {
                    "occupation_id": code,
                    "standard_name": standard_name,
                    "confidence": "high",
                    "rule_id": "V04_MANUAL_ALIAS",
                    "support_records": len(items),
                }
            audit.append({
                "job_title_normalized_v04": normalized,
                "records": len(items),
                "codes": "|".join(sorted(codes)),
                "statuses": "|".join(sorted(statuses)),
                "alias_status": reason,
            })
        return aliases, audit

    def _build_anchor_lookup(self) -> tuple[dict[str, dict], list[dict]]:
        rows = _read_csv(ANCHOR_PATH)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            normalized = normalize_title_v04(row["anchor_title"])
            if normalized:
                grouped[normalized].append(row)

        lookup: dict[str, dict] = {}
        candidates: list[dict] = []
        for normalized, items in grouped.items():
            codes = {row["occupation_id"] for row in items}
            if len(codes) != 1 or normalized in self.ambiguous_titles:
                continue
            row = items[0]
            item = {
                "candidate": normalized,
                "occupation_id": row["occupation_id"],
                "standard_name": row["anchor_title"],
                "source": "anchor_dictionary",
            }
            lookup[normalized] = item
            candidates.append(item)

        for normalized, row in self.manual_aliases.items():
            item = {
                "candidate": normalized,
                "occupation_id": row["occupation_id"],
                "standard_name": row["standard_name"],
                "source": "manual_alias",
            }
            lookup[normalized] = item
            candidates.append(item)
        return lookup, candidates

    def _result(
        self,
        code: str,
        standard_name: str,
        method: str,
        rule_id: str,
        confidence: str,
        status: str,
        normalized_title: str,
        score_top1: float = 0.0,
        score_top2: float = 0.0,
        score_margin: float = 0.0,
        review_flag: int = 0,
    ) -> dict:
        l1 = code[0] if code != "Z99" else "Z"
        return {
            "job_title_normalized": normalized_title,
            "occupation_l1": l1,
            "occupation_l1_name": self.l1_names[l1],
            "occupation_id": code,
            "occupation_name": self.occupation_names[code],
            "occupation_standard_name": standard_name,
            "occupation_method": method,
            "occupation_rule_id": rule_id,
            "occupation_confidence": confidence,
            "occupation_status": status,
            "occupation_review_flag": int(review_flag),
            "occupation_score_top1": float(score_top1),
            "occupation_score_top2": float(score_top2),
            "occupation_score_margin": float(score_margin),
            "occupation_version": VERSION,
        }

    def _match_context(self, title: str, description: str) -> dict | None:
        combined_description = unicodedata.normalize("NFKC", description or "").lower()
        for rule in self.context_rules:
            if not rule["title_re"].search(title):
                continue
            if rule["description_re"] is not None and not rule["description_re"].search(combined_description):
                continue
            if rule["exclude_re"] is not None and rule["exclude_re"].search(title + " " + combined_description):
                continue
            return rule
        return None

    def _fuzzy_match(self, title: str) -> tuple[dict | None, float, float, float, str]:
        if len(title) < self.fuzzy_minimum_length:
            return None, 0.0, 0.0, 0.0, "short_title_blocked"
        if re.fullmatch(r"[a-z0-9.+#-]+", title, flags=re.IGNORECASE) and len(title) <= 6:
            return None, 0.0, 0.0, 0.0, "short_ascii_blocked"

        choices = [item["candidate"] for item in self.fuzzy_candidates]
        matches = process.extract(title, choices, scorer=fuzz.ratio, limit=len(choices))
        best_by_group: dict[str, tuple[float, dict]] = {}
        for _, score, index in matches:
            item = self.fuzzy_candidates[index]
            previous = best_by_group.get(item["occupation_id"])
            if previous is None or score > previous[0]:
                best_by_group[item["occupation_id"]] = (float(score), item)
        ranked = sorted(best_by_group.values(), key=lambda pair: (-pair[0], pair[1]["occupation_id"]))
        if not ranked:
            return None, 0.0, 0.0, 0.0, "no_fuzzy_candidate"
        top1, item = ranked[0]
        top2 = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = top1 - top2
        if top1 >= self.fuzzy_threshold and margin >= self.fuzzy_minimum_margin:
            return item, top1, top2, margin, "fuzzy_anchor_accepted"
        if top1 >= 80:
            return None, top1, top2, margin, "fuzzy_80_89_review"
        return None, top1, top2, margin, "score_below_80"

    @lru_cache(maxsize=250_000)
    def classify(self, title_raw: str, description_raw: str = "", primary_category_raw: str = "") -> dict:
        title = normalize_title_v04(title_raw or "")
        description = "" if description_raw is None else str(description_raw)

        context = self._match_context(title, description)
        if context is not None:
            return self._result(
                context["occupation_id"], context["standard_name"], "context_rule",
                context["rule_id"], context["confidence"], "context_classified",
                title, review_flag=int(context["confidence"] != "high"),
            )

        alias = self.manual_aliases.get(title)
        if alias is not None:
            return self._result(
                alias["occupation_id"], alias["standard_name"], "manual_alias",
                alias["rule_id"], alias["confidence"], "manual_alias_accepted", title,
            )

        anchor = self.anchor_lookup.get(title)
        if anchor is not None:
            return self._result(
                anchor["occupation_id"], anchor["standard_name"], "exact_anchor", "",
                "high", "exact_anchor_accepted", title,
            )

        if not title:
            return self._result(
                "Z99", "", "unclassified", "", "unclassified", "empty_or_advertising_title",
                title, review_flag=1,
            )

        if title in self.ambiguous_titles:
            return self._result(
                "Z99", "", "unclassified", "", "unclassified", "ambiguous_title_needs_context",
                title, review_flag=1,
            )

        base = self.base_classifier(title, "")
        if base["occupation_id"] != "Z99":
            return self._result(
                base["occupation_id"], base["match_text"], "keyword_rule", base["rule_id"],
                base["confidence"], "keyword_classified", title,
                review_flag=int(base["confidence"] != "high"),
            )

        fuzzy_item, top1, top2, margin, fuzzy_status = self._fuzzy_match(title)
        if fuzzy_item is not None:
            return self._result(
                fuzzy_item["occupation_id"], fuzzy_item["standard_name"], "fuzzy_anchor", "",
                "medium", fuzzy_status, title, top1, top2, margin, review_flag=1,
            )

        # 初级分类只作为人工复核提示，不再自动生成occupation_id。
        fallback_target = ""
        primary = normalize_title_v04(primary_category_raw or "")
        if primary:
            fallback = self.base_classifier(primary, "")
            if fallback["occupation_id"] != "Z99":
                fallback_target = f"初级分类建议:{fallback['occupation_id']}:{fallback['match_text']}"
        return self._result(
            "Z99", fallback_target, "unclassified", "", "unclassified", fuzzy_status,
            title, top1, top2, margin, review_flag=1,
        )


def build_classifier() -> OccupationV04Classifier:
    return OccupationV04Classifier()

