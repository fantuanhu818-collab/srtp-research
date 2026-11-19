from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOFTWARE_RULES = PROJECT_ROOT / "config" / "software_skill_rules_v0.1.csv"
DEFAULT_TESTS = PROJECT_ROOT / "config" / "software_ai_boundary_test_cases_v0.1.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "qc"
REPO_AI_DICTIONARY = PROJECT_ROOT / "config" / "ai_skill_dictionary_v1.0.json"
EXTERNAL_AI_DICTIONARY = Path(
    r"D:\SRTP中期\AI鎶€鑳借瘝鍏竉v1.0\ai_skill_dictionary_v1.0.json"
)
DEFAULT_AI_DICTIONARY = (
    REPO_AI_DICTIONARY if REPO_AI_DICTIONARY.exists() else EXTERNAL_AI_DICTIONARY
)

REQUIRED_RULE_COLUMNS = {
    "rule_id",
    "skill_group",
    "software_subgroup",
    "term_level",
    "standard_term",
    "aliases",
    "pattern",
    "exclude_pattern",
    "title_allowed",
    "requires_skill_cue",
    "term_source",
    "review_status",
    "notes",
}

ALLOWED_SUBGROUPS = {
    "programming",
    "database",
    "devops",
    "data_stats",
    "engineering_design",
    "enterprise",
    "office_basic",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查一般软件技能词典与AI技能词典的词条边界和测试样例。"
    )
    parser.add_argument("--software-rules", type=Path, default=DEFAULT_SOFTWARE_RULES)
    parser.add_argument("--ai-dictionary", type=Path, default=DEFAULT_AI_DICTIONARY)
    parser.add_argument("--tests", type=Path, default=DEFAULT_TESTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s_\-/]+", "", value)


def validate_software_rules(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        raise ValueError("软件技能词典为空")
    missing = REQUIRED_RULE_COLUMNS - set(rows[0])
    if missing:
        raise ValueError(f"软件技能词典缺少字段: {sorted(missing)}")

    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}
    duplicate_aliases: list[dict[str, str]] = []
    for row in rows:
        rule_id = row["rule_id"]
        if rule_id in seen_ids:
            raise ValueError(f"软件技能规则ID重复: {rule_id}")
        seen_ids.add(rule_id)
        if row["skill_group"] != "software":
            raise ValueError(f"{rule_id} 的 skill_group 不是 software")
        if row["software_subgroup"] not in ALLOWED_SUBGROUPS:
            raise ValueError(f"{rule_id} 的软件子类不合法")
        if row["term_level"] not in {"strict", "conditional"}:
            raise ValueError(f"{rule_id} 的规则层级不合法")
        if row["title_allowed"] not in {"0", "1"}:
            raise ValueError(f"{rule_id} 的 title_allowed 不合法")
        if row["requires_skill_cue"] not in {"0", "1"}:
            raise ValueError(f"{rule_id} 的 requires_skill_cue 不合法")
        re.compile(row["pattern"], flags=re.IGNORECASE)
        if row["exclude_pattern"]:
            re.compile(row["exclude_pattern"], flags=re.IGNORECASE)

        for alias in filter(None, (part.strip() for part in row["aliases"].split(";"))):
            key = normalize(alias)
            previous = seen_aliases.get(key)
            if previous and previous != rule_id:
                duplicate_aliases.append(
                    {
                        "conflict_type": "software_alias_duplicate",
                        "software_rule_id": rule_id,
                        "software_term": row["standard_term"],
                        "ai_rule_id": "",
                        "ai_tier": "",
                        "matched_text": alias,
                        "detail": f"与软件规则 {previous} 的别名重复",
                    }
                )
            else:
                seen_aliases[key] = rule_id
    return duplicate_aliases


def compile_ai_pattern(term: dict[str, object]) -> re.Pattern[str]:
    pattern = str(term["pattern"])
    if bool(term.get("word")):
        pattern = rf"(?<![A-Za-z0-9])(?:{pattern})(?![A-Za-z0-9])"
    return re.compile(pattern, flags=re.IGNORECASE)


def ai_literal_candidates(term: dict[str, object]) -> set[str]:
    candidates: set[str] = set()
    source_skill = term.get("source_skill")
    if isinstance(source_skill, str) and source_skill.strip():
        candidates.add(source_skill.strip())
    pattern = str(term.get("pattern", ""))
    for part in pattern.split("|"):
        item = part.strip()
        if not item or re.search(r"[\[\](){}?*+.^$\\]", item):
            continue
        candidates.add(item)
    return candidates


def find_cross_dictionary_conflicts(
    software_rows: list[dict[str, str]], ai_terms: list[dict[str, object]]
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    ai_compiled = [(term, compile_ai_pattern(term)) for term in ai_terms]

    for software in software_rows:
        software_pattern = re.compile(software["pattern"], flags=re.IGNORECASE)
        software_exclude = (
            re.compile(software["exclude_pattern"], flags=re.IGNORECASE)
            if software["exclude_pattern"]
            else None
        )
        aliases = [part.strip() for part in software["aliases"].split(";") if part.strip()]

        for alias in aliases:
            for ai_term, ai_pattern in ai_compiled:
                match = ai_pattern.search(alias)
                if not match:
                    continue
                if normalize(match.group(0)) != normalize(alias):
                    continue
                key = (software["rule_id"], str(ai_term["id"]), alias, "alias_matched_by_ai")
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    {
                        "conflict_type": "alias_matched_by_ai",
                        "software_rule_id": software["rule_id"],
                        "software_term": software["standard_term"],
                        "ai_rule_id": str(ai_term["id"]),
                        "ai_tier": str(ai_term["tier"]),
                        "matched_text": alias,
                        "detail": "软件别名被AI规则完整匹配",
                    }
                )

        for ai_term, _ in ai_compiled:
            for candidate in ai_literal_candidates(ai_term):
                match = software_pattern.search(candidate)
                if not match:
                    continue
                if software_exclude and software_exclude.search(candidate):
                    continue
                key = (
                    software["rule_id"],
                    str(ai_term["id"]),
                    candidate,
                    "ai_literal_matched_by_software",
                )
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    {
                        "conflict_type": "ai_literal_matched_by_software",
                        "software_rule_id": software["rule_id"],
                        "software_term": software["standard_term"],
                        "ai_rule_id": str(ai_term["id"]),
                        "ai_tier": str(ai_term["tier"]),
                        "matched_text": candidate,
                        "detail": "AI词条的可读名称被软件规则匹配",
                    }
                )
    return conflicts


def software_match(text: str, rows: list[dict[str, str]]) -> tuple[int, str]:
    for row in rows:
        pattern = re.compile(row["pattern"], flags=re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            continue
        if row["exclude_pattern"] and re.search(row["exclude_pattern"], text, flags=re.IGNORECASE):
            continue
        return 1, row["rule_id"]
    return 0, ""


def ai_match(
    text: str,
    terms: list[dict[str, object]],
    exclusions: list[dict[str, object]],
) -> tuple[int, str]:
    excluded_ids: set[str] = set()
    for exclusion in exclusions:
        if re.search(str(exclusion["clause_pattern"]), text, flags=re.IGNORECASE):
            excluded_ids.update(str(item) for item in exclusion["terms"])

    strict_hits: list[str] = []
    conditional_hits: list[str] = []
    for term in terms:
        term_id = str(term["id"])
        if term_id in excluded_ids:
            continue
        if not compile_ai_pattern(term).search(text):
            continue
        if term["tier"] == "strict":
            strict_hits.append(term_id)
        elif term["tier"] == "conditional":
            conditional_hits.append(term_id)

    ai_value = int(bool(strict_hits) or len(set(conditional_hits)) >= 2)
    hits = strict_hits + conditional_hits
    return ai_value, "|".join(hits)


def run_tests(
    tests: list[dict[str, str]],
    software_rows: list[dict[str, str]],
    ai_terms: list[dict[str, object]],
    ai_exclusions: list[dict[str, object]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for test in tests:
        software_value, software_rule = software_match(test["text"], software_rows)
        ai_value, ai_rules = ai_match(test["text"], ai_terms, ai_exclusions)
        expected_software = int(test["expected_software"])
        expected_ai = int(test["expected_ai"])
        passed = software_value == expected_software and ai_value == expected_ai
        results.append(
            {
                **test,
                "actual_software": software_value,
                "actual_ai": ai_value,
                "software_rule_id": software_rule,
                "ai_rule_ids": ai_rules,
                "result": "PASS" if passed else "FAIL",
            }
        )
    return results


def main() -> int:
    args = parse_args()
    software_path = args.software_rules.resolve()
    ai_path = args.ai_dictionary.resolve()
    tests_path = args.tests.resolve()
    output_dir = args.output_dir.resolve()

    for path in (software_path, ai_path, tests_path):
        if not path.exists():
            raise FileNotFoundError(path)

    software_rows = read_csv(software_path)
    conflicts = validate_software_rules(software_rows)
    ai_dictionary = json.loads(ai_path.read_text(encoding="utf-8"))
    ai_terms = ai_dictionary.get("terms", [])
    ai_exclusions = ai_dictionary.get("term_exclusions", [])
    if not ai_terms:
        raise ValueError("AI词典没有terms")

    conflicts.extend(find_cross_dictionary_conflicts(software_rows, ai_terms))
    tests = read_csv(tests_path)
    test_results = run_tests(tests, software_rows, ai_terms, ai_exclusions)

    conflict_path = output_dir / "software_ai_dictionary_boundary_v0.1_conflicts.csv"
    test_result_path = output_dir / "software_ai_dictionary_boundary_v0.1_test_results.csv"
    report_path = output_dir / "software_ai_dictionary_boundary_v0.1_report.md"

    conflict_fields = [
        "conflict_type",
        "software_rule_id",
        "software_term",
        "ai_rule_id",
        "ai_tier",
        "matched_text",
        "detail",
    ]
    write_csv(conflict_path, conflicts, conflict_fields)
    write_csv(
        test_result_path,
        test_results,
        [
            "test_id",
            "text",
            "expected_software",
            "expected_ai",
            "focus",
            "actual_software",
            "actual_ai",
            "software_rule_id",
            "ai_rule_ids",
            "result",
        ],
    )

    subgroup_counts: dict[str, int] = {}
    for row in software_rows:
        subgroup_counts[row["software_subgroup"]] = subgroup_counts.get(row["software_subgroup"], 0) + 1
    strict_count = sum(row["term_level"] == "strict" for row in software_rows)
    conditional_count = sum(row["term_level"] == "conditional" for row in software_rows)
    failed_tests = [row for row in test_results if row["result"] == "FAIL"]
    status = "PASS" if not conflicts and not failed_tests else "FAIL"

    subgroup_lines = "\n".join(
        f"- `{name}`：{count}条；" for name, count in sorted(subgroup_counts.items())
    )
    report = f"""# 软件技能词典与AI词典边界检查v0.1

结论：`{status}`。

本检查只验证词典结构、词条归属和预设边界样例，不代替真实招聘数据试跑和人工准确性复核。

## 1. 输入

- 软件词典：`{software_path}`；
- 软件词典SHA256：`{sha256(software_path)}`；
- AI词典：`{ai_path}`；
- AI词典版本：`{ai_dictionary.get('rule_version', '')}`；
- AI词典SHA256：`{sha256(ai_path)}`；
- 边界测试：`{tests_path}`。

## 2. 词典规模

- 软件规则：{len(software_rows)}条；
- 严格词规则：{strict_count}条；
- 条件词规则：{conditional_count}条；
- AI词条：{len(ai_terms)}条。

软件子类：

{subgroup_lines}

## 3. 检查结果

- 未解决词典冲突：{len(conflicts)}条；
- 边界测试：{len(test_results)}条；
- 通过：{len(test_results) - len(failed_tests)}条；
- 失败：{len(failed_tests)}条。

词典冲突明细见`{conflict_path.relative_to(PROJECT_ROOT)}`，测试结果见`{test_result_path.relative_to(PROJECT_ROOT)}`。

## 4. 当前边界

- Python、Java、SQL、Linux、Office、Excel等归一般软件技能；
- TensorFlow、PyTorch、Keras、OpenCV、LLM、RAG等归AI技能；
- 一条广告允许AI技能与软件技能同时为1；
- Office等基础办公软件进入主软件变量，同时保留`office_basic`子类；
- “软件工程师”“数据分析师”等宽泛岗位名称不能单独命中；
- 本轮尚未运行真实招聘数据，所有软件规则仍为`draft_v0.1`。

## 5. 下一步

1. 项目组阅读规则表和边界报告；
2. 确认后编写2022年软件技能识别程序；
3. 在真实数据中检查高频词、典型误判和基础办公软件占比；
4. 生成三类非AI技能统一人工复核表。
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"SOFTWARE_RULES={len(software_rows)}")
    print(f"AI_TERMS={len(ai_terms)}")
    print(f"BOUNDARY_CONFLICTS={len(conflicts)}")
    print(f"BOUNDARY_TESTS_PASS={len(test_results) - len(failed_tests)}/{len(test_results)}")
    print(f"SOFTWARE_AI_BOUNDARY={status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
