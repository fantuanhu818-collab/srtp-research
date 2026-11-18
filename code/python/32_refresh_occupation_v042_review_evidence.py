"""将V4.2复核样本中的内部正则表达式改为实际命中的中文/英文词。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "occupation_evidence_rules_v0.4.2.json"
REVIEW_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "occupation_v042_rule_development_20261118"
    / "occupation_v042_2022_manual_review_sample_400.csv"
)


def normalize(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return re.sub(r"\s+", "", text)


def actual_matches(patterns: list[str], text: str) -> list[str]:
    matches: list[str] = []
    for raw in patterns:
        match = re.search(raw, text, flags=re.IGNORECASE)
        if match is not None and match.group(0) not in matches:
            matches.append(match.group(0))
    return matches


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rules = {item["occupation_id"]: item for item in config["rules"]}
    frame = pd.read_csv(REVIEW_PATH, encoding="utf-8-sig", dtype=str).fillna("")

    for index, row in frame.iterrows():
        rule = rules.get(row["candidate_occupation_id"])
        if rule is None:
            continue
        title = normalize(row["job_title_normalized"])
        description = normalize(row["job_description_excerpt"])
        primary = normalize(row["primary_category"])

        title_hits = actual_matches(rule.get("title_decisive", []), title)
        if not title_hits:
            title_hits = actual_matches(rule.get("title_strong", []), title)
        strong_hits = actual_matches(rule.get("description_strong", []), description)
        support_hits = actual_matches(rule.get("description_support", []), description)
        primary_hits = actual_matches(rule.get("primary_patterns", []), primary)

        frame.at[index, "title_evidence"] = "；".join(title_hits)
        frame.at[index, "description_strong_evidence"] = (
            "；".join(strong_hits)
            if strong_hits or not row["description_strong_evidence"]
            else "完整职位描述后文命中（当前切片未显示）"
        )
        frame.at[index, "description_support_evidence"] = (
            "；".join(support_hits)
            if support_hits or not row["description_support_evidence"]
            else "完整职位描述后文命中（当前切片未显示）"
        )
        frame.at[index, "primary_evidence"] = "；".join(primary_hits)

    frame.to_csv(REVIEW_PATH, index=False, encoding="utf-8-sig")
    evidence_columns = [
        "title_evidence",
        "description_strong_evidence",
        "description_support_evidence",
        "primary_evidence",
    ]
    regex_markers = frame[evidence_columns].apply(
        lambda column: column.str.contains(r"\(\?:|\.\{|\[\^|\\[+*?.]", regex=True).sum()
    )
    print(f"ROWS={len(frame)}")
    print(f"REGEX_MARKERS_REMAINING={int(regex_markers.sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
