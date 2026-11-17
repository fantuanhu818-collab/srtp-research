"""生成AI技能人工标注表（盲标、按ChatGPT发布前后分层、两人重叠50条）。

输入：<features_root>/ai_skill_v1（程序结果）与 <curated_root>/cleaned_v1（原文、发布日期），只读。
输出（含广告原文，均不进Git）：<analysis_root>/ai_annotation_v1/
  标注表_A.csv、标注表_B.csv   只有岗位名称和职位描述，不显示程序结果
  annotation_key.csv            编号→来源记录ID、分层、程序结果（标注完成前不要打开）
输出（无原文，进Git）：outputs/qc/ai_annotation_v1_strata.csv  各层总体数量和抽样数（计算加权指标用）

用法：.venv/bin/python code/python/14_make_annotation_sheets.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED = 20261116
CHATGPT_RELEASE = "2022-11-30"
OVERLAP = 50
TECH_TITLE = "工程师|开发|算法|数据|研发|技术|程序|软件"
# (层名, 条件, 每个时期抽样数)。阳性层用于查准率；未命中层（含技术岗）用于查全率。
STRATA = [
    ("strict_hit", "ai_skill = 1", 50),
    ("broad_only", "ai_skill = 0 AND ai_skill_broad = 1", 30),
    ("intro_only", "ai_skill = 0 AND ai_skill_broad = 0 AND ai_intro_only = 1", 15),
    ("review_only", "ai_skill = 0 AND ai_skill_broad = 0 AND ai_intro_only = 0 AND ai_review_flag = 1", 15),
    ("no_hit_tech", f"ai_skill = 0 AND ai_skill_broad = 0 AND ai_intro_only = 0 AND ai_review_flag = 0 "
                    f"AND regexp_matches(job_title, '{TECH_TITLE}')", 15),
    ("no_hit_other", f"ai_skill = 0 AND ai_skill_broad = 0 AND ai_intro_only = 0 AND ai_review_flag = 0 "
                     f"AND NOT regexp_matches(coalesce(job_title, ''), '{TECH_TITLE}')", 25),
]
PERIODS = {"pre": f"pub_date < DATE '{CHATGPT_RELEASE}'", "post": f"pub_date >= DATE '{CHATGPT_RELEASE}'"}


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")  # BOM：Excel/WPS打开中文不乱码


def main() -> int:
    storage = json.loads((PROJECT_ROOT / "config" / "storage_paths.json").read_text(encoding="utf-8"))
    ai = sql_path(Path(storage["features_root"]) / "ai_skill_v1" / "jobs_*_ai_skill.parquet")
    text = sql_path(Path(storage["curated_root"]) / "cleaned_v1" / "jobs_*_cleaned.parquet")
    out_dir = Path(storage["analysis_root"]) / "ai_annotation_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SELECT setseed({(SEED % 1000) / 1000})")
    con.execute(f"""CREATE TEMP TABLE base AS
        SELECT a.*, t."招聘岗位" AS job_title, t."职位描述" AS job_description, t."招聘发布日期" AS pub_date
        FROM read_parquet('{ai}') a JOIN read_parquet('{text}') t ON t."来源记录ID" = a.source_record_id
        WHERE a.ai_status IN ('positive', 'negative')""")

    pop_rows, parts = [], []
    for period, pcond in PERIODS.items():
        for name, cond, size in STRATA:
            where = f"({cond}) AND {pcond}"
            n_pop = con.execute(f"SELECT count(*) FROM base WHERE {where}").fetchone()[0]
            pop_rows.append({"period": period, "stratum": name, "population": n_pop, "sampled": min(size, n_pop)})
            parts.append(con.execute(f"""SELECT '{period}' AS period, '{name}' AS stratum, * FROM base
                WHERE {where} ORDER BY random() LIMIT {size}""").df())
    sample = pd.concat(parts, ignore_index=True)
    assert sample["source_record_id"].is_unique

    rng = random.Random(SEED)
    order = list(range(len(sample)))
    rng.shuffle(order)
    sample = sample.iloc[order].reset_index(drop=True)
    sample.insert(0, "annotation_no", range(1, len(sample) + 1))

    # 前OVERLAP条两人都标（计算一致率），其余对半分。打乱后前50条在各层中随机分布。
    rest = sample.iloc[OVERLAP:]
    a_ids = set(sample.annotation_no[:OVERLAP]) | set(rest.annotation_no[::2])
    b_ids = set(sample.annotation_no[:OVERLAP]) | set(rest.annotation_no[1::2])
    blind_cols = {"annotation_no": "编号", "job_title": "招聘岗位", "job_description": "职位描述"}
    for who, ids in (("A", a_ids), ("B", b_ids)):
        sheet = sample[sample.annotation_no.isin(ids)][list(blind_cols)].rename(columns=blind_cols)
        sheet = sheet.sample(frac=1, random_state=SEED + ord(who)).reset_index(drop=True)
        sheet["是否要求AI技能(1/0/9)"] = ""
        sheet["AI类型(traditional/generative/both)"] = ""
        sheet["备注"] = ""
        write_csv(sheet, out_dir / f"标注表_{who}.csv")
        print(f"SHEET_{who} rows={len(sheet)}")

    key = sample[["annotation_no", "source_record_id", "year", "period", "stratum", "ai_skill", "ai_skill_broad",
                  "ai_hit_terms", "ai_broad_terms", "ai_evidence", "ai_rule_version"]].copy()
    key["overlap"] = key.annotation_no <= OVERLAP
    key["annotator"] = key.annotation_no.map(lambda n: "A+B" if n <= OVERLAP else ("A" if n in a_ids else "B"))
    write_csv(key, out_dir / "annotation_key.csv")
    pop = pd.DataFrame(pop_rows)
    pop.to_csv(PROJECT_ROOT / "outputs" / "qc" / "ai_annotation_v1_strata.csv", index=False, encoding="utf-8-sig")
    print(pop.to_string(index=False))
    print(f"TOTAL_SAMPLE={len(sample)} OUT={out_dir}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
