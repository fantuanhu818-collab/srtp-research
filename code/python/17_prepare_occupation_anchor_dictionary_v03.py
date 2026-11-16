"""生成v0.3粗职业分类使用的初版职业名称词典。

词典不是职业大典小类的替代品：每个名称都直接对应项目的37个职业组。
本脚本带入v0.2中已人工确认的招聘别名；优先按别名本身的旧规则方向映射。
职业大典正式名称与招聘名称的词面差异很大，不能把“是否命中旧规则”当作保留条件。
只有别名和其官方名称都无法判断的记录才不自动加入，留待人工复核后再扩展。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("SRTP_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
ALIAS_PATH = PROJECT_ROOT / "config" / "occupation_aliases_v0.2.csv"
OUTPUT_PATH = PROJECT_ROOT / "config" / "occupation_name_dictionary_v0.3.csv"
QC_PATH = PROJECT_ROOT / "outputs" / "qc" / "occupation_v03_anchor_dictionary_summary.csv"

# 这两个名称的v0.2人工备注已明确为“软件开发岗位”，但v0.1规则缺少单独的Java/后端工程师词条。
# 显式写出而不是让程序凭相似度猜测，便于后续复核和修改。
MANUAL_GROUP_OVERRIDES = {
    "Java工程师": "D01",
    "后端工程师": "D01",
}


def load_classifier():
    module_path = PROJECT_ROOT / "code" / "python" / "12_pilot_occupation_2022.py"
    spec = importlib.util.spec_from_file_location("occupation_v01_pilot", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入v0.1职业分类器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    classifier, _ = module.build_classifier(config)
    return classifier, module.normalize_title, config


def main() -> int:
    classifier, normalize_title, config = load_classifier()
    aliases = pd.read_csv(ALIAS_PATH, dtype="string").fillna("")
    aliases = aliases.loc[
        aliases["alias_source"].eq("manual_v0.2")
        & aliases["review_status"].eq("curated_v0.2")
    ].copy()
    if aliases.empty:
        raise RuntimeError("未找到可继承的人工确认别名")

    rows: list[dict] = []
    excluded: list[dict] = []
    for record in aliases.to_dict("records"):
        alias_result = classifier(record["alias"], "")
        official_text = record["occupation_fine_name"] or record["occupation_small_name"]
        official_result = classifier(official_text, "") if official_text else {"occupation_id": "Z99"}
        alias_id = alias_result["occupation_id"]
        official_id = official_result["occupation_id"]
        if alias_id != "Z99":
            occupation_id = alias_id
            mapping_basis = "alias_v0.1_rule"
        elif record["alias"] in MANUAL_GROUP_OVERRIDES:
            occupation_id = MANUAL_GROUP_OVERRIDES[record["alias"]]
            mapping_basis = "explicit_manual_override"
        elif official_id != "Z99":
            occupation_id = official_id
            mapping_basis = "official_name_v0.1_rule"
        else:
            excluded.append({
                "alias": record["alias"], "alias_normalized": record["alias_normalized"],
                "alias_occupation_id": alias_id, "official_occupation_id": official_id,
                "reason": "别名和职业大典名称均无法可靠归入37组",
            })
            continue
        rows.append({
            "anchor_title": record["alias"],
            "anchor_normalized": normalize_title(record["alias"]),
            "occupation_id": occupation_id,
            "occupation_name": config["occupation_names"][occupation_id],
            "occupation_l1": occupation_id[0],
            "occupation_l1_name": config["l1_names"][occupation_id[0]],
            "anchor_source": "v0.2人工确认别名",
            "mapping_basis": mapping_basis,
            "review_status": "carried_forward_confirmed",
            "notes": record["notes"],
        })

    dictionary = pd.DataFrame(rows).drop_duplicates(["anchor_normalized", "occupation_id"])
    conflicts = dictionary.groupby("anchor_normalized")["occupation_id"].nunique()
    conflict_titles = set(conflicts.loc[conflicts.gt(1)].index)
    if conflict_titles:
        dictionary = dictionary.loc[~dictionary["anchor_normalized"].isin(conflict_titles)].copy()
        excluded.extend({
            "alias": title, "alias_normalized": title, "alias_occupation_id": "",
            "official_occupation_id": "", "reason": "同一别名对应多个职业组",
        } for title in sorted(conflict_titles))
    if dictionary.empty:
        raise RuntimeError("v0.3职业名称词典为空")
    dictionary = dictionary.sort_values(["occupation_id", "anchor_normalized"]).reset_index(drop=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dictionary.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    summary = (
        dictionary.groupby(["occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name"])
        .size().rename("anchor_count").reset_index().sort_values("occupation_id")
    )
    summary.to_csv(QC_PATH, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    excluded_path = QC_PATH.with_name("occupation_v03_anchor_dictionary_excluded.csv")
    pd.DataFrame(excluded).to_csv(excluded_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    print(f"ANCHOR_DICTIONARY={OUTPUT_PATH}")
    print(f"ANCHORS={len(dictionary)}")
    print(f"EXCLUDED={len(excluded)}")
    print("OCCUPATION_V03_ANCHORS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
