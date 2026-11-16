"""生成结构与正式分析数据相同的假DTA，只用于测试描述统计程序能否跑通。

数字全部随机生成，不代表任何真实结果，不得用于分析或汇报。
用法：.venv/bin/python code/python/tests/make_fake_analysis_dta.py <输出.dta> [行数]
"""

import sys

import numpy as np
import pandas as pd

out = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 300_000
rng = np.random.default_rng(20261116)

year = rng.choice(np.arange(2018, 2026), n)
month = rng.integers(1, 13, n)
ym = pd.to_datetime({"year": year, "month": month, "day": 1})
t = (year - 2018) + (month - 1) / 12
p_ai = 0.01 + 0.004 * t
ai = (rng.random(n) < p_ai).astype("float64")
after_gpt = ym >= pd.Timestamp("2022-11-01")
genai = np.where(ai == 1, (rng.random(n) < np.where(after_gpt, 0.5, 0.02)), 0).astype("float64")
broad = np.maximum(ai, rng.random(n) < 0.01).astype("float64")
missing = rng.random(n) < 0.001
for arr in (ai, genai, broad):
    arr[missing] = np.nan

edu = rng.choice(["不限", "高中及以下", "大专", "本科", "硕士", "博士"], n, p=[.15, .15, .3, .32, .07, .01]).astype(object)
exp = rng.choice(["不限/应届", "1年以内", "1—3年", "3—5年", "5年以上"], n, p=[.3, .1, .3, .2, .1]).astype(object)
edu[rng.random(n) < 0.005] = ""
exp[rng.random(n) < 0.004] = ""
city = rng.choice(["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安", "苏州"] + [f"城市{i}" for i in range(40)], n).astype(object)
city[rng.random(n) < 0.005] = ""
ln_wage = 8.8 + 0.03 * t + 0.25 * np.nan_to_num(ai) + rng.normal(0, 0.5, n)

df = pd.DataFrame({
    "source_record_id": [f"{y}-fake-{i:09d}" for i, y in enumerate(year)],
    "year": year.astype("int16"),
    "year_month": ym,
    "wage_mid": np.exp(ln_wage).round(0),
    "education": edu, "experience": exp, "city_id": city,
    "firm_id": rng.choice([f"{i:06d}" for i in range(1, 500)], n),
    "industry_id": rng.choice(["制造业", "信息技术", "金融", "批发零售", "房地产"], n),
    "ai_skill": ai, "ai_skill_broad": broad, "ai_genai": genai,
    "ai_traditional": np.where(ai == 1, 1 - genai, np.where(np.isnan(ai), np.nan, 0)),
})
df["ln_wage"] = np.log(df["wage_mid"])
df.to_stata(out, write_index=False, version=118, convert_dates={"year_month": "td"})
print(f"FAKE_DTA rows={n} -> {out}")
