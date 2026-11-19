"""为描述性统计生成Stata输入DTA（B，中期临时接口）。

合并：confirmed_core_v2（A的核心变量）+ ai_skill_v1（AI技能线当前版本）
     + wage_fix_v3（A的工资修正，11-19）+ cleaned_v1 的 来源（平台）和 上市公司行业。
工资：wage_mid、ln_wage 改用 wage_fix_v3 的修正值（年薪误录÷12、量级÷10、面议占位和无法修正的置缺失）；
     原值保留为 wage_mid_orig，wage_fix_flag：0未改、1已修正、2置缺失。
职业变量 occupation_id 尚未放入（等A的v0.4定稿）。

用法：.venv/bin/python code/python/30_build_descriptive_input.py 2022
      .venv/bin/python code/python/30_build_descriptive_input.py all
输出：<stata_data_root>/descriptive_input_<2022|all>.dta
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
storage = json.loads((ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
FEAT = Path(storage["features_root"])
CLEAN = Path(storage["curated_root"]) / "cleaned_v1"
OUT = Path(storage["stata_data_root"])

AI_COLS = ["source_record_id", "year", "ai_skill", "ai_skill_broad", "ai_genai", "ai_traditional"]
WAGE_FIX = "wage_fix_v3"
WAGE_COLS = ["source_record_id", "wage_mid_orig", "wage_mid_fixed", "ln_wage_fixed", "wage_fix_flag"]


def one_year(year: int) -> pd.DataFrame:
    core = pd.read_parquet(FEAT / "confirmed_core_v2" / f"jobs_{year}_confirmed_core.parquet")
    ai = pd.read_parquet(FEAT / "ai_skill_v1" / f"jobs_{year}_ai_skill.parquet", columns=AI_COLS)
    raw = pd.read_parquet(CLEAN / f"jobs_{year}_cleaned.parquet", columns=["来源记录ID", "来源", "上市公司行业"])
    raw = raw.rename(columns={"来源记录ID": "source_record_id", "来源": "platform", "上市公司行业": "industry_id"})

    wf = pd.read_parquet(FEAT / WAGE_FIX / f"jobs_{year}_wage_fix.parquet", columns=WAGE_COLS)

    df = core.merge(ai, on="source_record_id", how="left", validate="1:1")
    df = df.merge(wf, on="source_record_id", how="left", validate="1:1")
    assert df["wage_fix_flag"].notna().all(), f"{year}: 有记录在{WAGE_FIX}中找不到"
    assert (df["wage_mid"] - df["wage_mid_orig"]).abs().max() < 1e-6, f"{year}: 核心变量工资与{WAGE_FIX}原值不一致"
    df["wage_mid"] = df.pop("wage_mid_fixed")
    df["ln_wage"] = df.pop("ln_wage_fixed")
    df["wage_fix_flag"] = df["wage_fix_flag"].astype("int8")
    df = df.merge(raw, on="source_record_id", how="left", validate="1:1")
    assert len(df) == len(core), "合并后行数变化"
    missing_ai = df["ai_skill"].isna() & df["year"].isna()
    assert not missing_ai.any(), f"{year}: {missing_ai.sum()} 条记录在ai_skill_v1中找不到"
    df["year"] = year
    df["platform"] = df["platform"].astype("string").fillna("").astype(str)
    df["industry_id"] = df["industry_id"].astype("string").fillna("").astype(str)
    for c in ["ai_skill", "ai_skill_broad", "ai_genai", "ai_traditional"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    for c in ["source_record_id", "education", "experience", "firm_id", "city_id"]:
        df[c] = df[c].astype("string").fillna("").astype(str)
    df["year_month"] = df["year_month"].astype(str)
    print(f"{year}: rows={len(df):,} ai_share={df['ai_skill'].mean():.4%} "
          f"wage_fixed={(df['wage_fix_flag'] == 1).sum():,} wage_missing={(df['wage_fix_flag'] == 2).sum():,}")
    return df


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "2022"
    years = list(range(2018, 2026)) if arg == "all" else [int(arg)]
    df = pd.concat([one_year(y) for y in years], ignore_index=True)
    assert df["source_record_id"].is_unique
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"descriptive_input_{arg}.dta"
    df.to_stata(path, write_index=False, version=118)
    print(f"ROWS={len(df):,}\nDTA={path}")
    if arg == "all":
        platform_table()
    return 0


def platform_table() -> None:
    """年份×平台的样本量与AI占比（汇总数字，可进Git）。"""
    df = pd.read_stata(OUT / "descriptive_input_all.dta", columns=["year", "platform", "ai_skill", "ln_wage"])
    t = (df.groupby(["year", "platform"])
           .agg(n=("ai_skill", "size"), ai_share=("ai_skill", "mean"), ln_wage_mean=("ln_wage", "mean"))
           .reset_index())
    t["share_of_year"] = t["n"] / t.groupby("year")["n"].transform("sum")
    path = ROOT / "outputs" / "analysis" / "descriptive_all" / "tables" / "t10_by_year_platform.csv"
    t.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"PLATFORM_TABLE={path}")


if __name__ == "__main__":
    sys.exit(main())
