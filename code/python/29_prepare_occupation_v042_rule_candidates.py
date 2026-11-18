"""提取V4.1高频Z99岗位，并生成V4.2名称规则候选表。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
BASE_RULE_PATH = PROJECT_ROOT / "config" / "occupation_rules_v0.1.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "occupation_v042_rule_development_20261118"
CANDIDATE_PATH = OUTPUT_DIR / "occupation_v042_top5000_z99_rule_candidates.csv"
SUMMARY_PATH = OUTPUT_DIR / "occupation_v042_title_rule_family_summary.csv"
CONTEXT_PATH = OUTPUT_DIR / "occupation_v042_context_priority_titles.csv"
REPORT_PATH = OUTPUT_DIR / "occupation_v042_candidate_report.md"


# 这里只生成候选，不会直接改写正式occupation_id。
# 顺序很重要：更具体的职业词放在更通用的词之前。
TITLE_RULES = [
    ("T_D02_DATA_ENGINEERING", "D02", "数据工程与商业智能", r"大数据架构师|数据架构师|数据仓库|数据开发|数据工程师|bi工程师|etl工程师"),
    ("T_D03_ALGORITHM", "D03", "算法与数据科学", r"算法工程师|机器学习|深度学习|自然语言处理|nlp工程师|推荐算法|搜索算法"),
    ("T_D01_SOFTWARE_LANGUAGE", "D01", "软件开发语言与平台", r"web前端|前端开发|web开发|java(?:架构师|开发|工程师|技术经理)|python(?:开发|工程师)?$|php(?:开发|工程师)?$|android(?:开发|工程师)?$|ios(?:开发|工程师)?$|c\+\+(?:开发|工程师)?$|c#(?:开发|工程师)?$|\.net(?:开发|工程师)?$|h5开发|u3d开发|unity3d开发|gis开发|全栈开发|后台开发|系统开发工程师|c语言开发"),
    ("T_D04_SOFTWARE_TEST", "D04", "软件与游戏测试", r"游戏测试|软件测试|测试开发|自动化测试|接口测试|性能测试"),
    ("T_D05_IT_OPERATION", "D05", "IT运维与网络安全", r"网络运维|系统运维|数据库运维|服务器运维|云运维|信息安全|网络安全|it主管"),
    ("T_D06_IMPLEMENTATION_SUPPORT", "D06", "IT实施交付与技术支持", r"软件交付|实施交付|系统实施|软件实施|it技术支持|系统技术支持"),
    ("T_E01_ELECTRONIC_HARDWARE", "E01", "电子硬件与自动化", r"pcb\s*layout|pcblayout|数字ic设计|模拟ic设计|射频ic设计|芯片设计|天线工程师|光学设计工程师|自控工程师|液压工程师|驱动工程师|cae工程师"),
    ("T_P01_PROCESS_MANUFACTURING", "P01", "生产制造与工艺", r"npi工程师|注塑(?:技术员|工程师)|smt(?:技术员|工程师)|生产工人|包装工$|模具设计|仪表工"),
    ("T_P02_QUALITY_INSPECTION", "P02", "质量检验与安全", r"^ipqc$|^iqc$|^oqc$|失效分析工程师|三坐标测量员|质量检验员|质量检测员"),
    ("T_P03_SUPPLY_CHAIN", "P03", "采购与供应链", r"外贸跟单员?|业务跟单|采购跟单|供应商开发|采购工程师|物料计划"),
    ("T_P04_LOGISTICS", "P04", "物流仓储与调度", r"关务专员|仓库账务员|库存账务员|物流调度|运输调度|仓库管理员"),
    ("T_C01_CONSTRUCTION", "C01", "建筑土木与工程建设", r"弱电工程师|bim工程师|精装修工程师|基建工程师|管道工程师|暖通工程师|土建工程师"),
    ("T_C03_VISUAL_DESIGN", "C03", "视觉与工业设计", r"^美工$|美术指导|工业设计师|ui设计师|视觉设计师|交互设计师"),
    ("T_B01_SALES", "B01", "销售与客户开发", r"客户代表|销售顾问|课程顾问|业务拓展经理|渠道销售|电话销售|otc代表|医药代表"),
    ("T_B02_MARKETING", "B02", "市场推广与品牌", r"市场策划|营销策划|广告优化师|信息流优化师|网络推广|品牌推广|市场推广"),
    ("T_B04_PRODUCT_GAME", "B04", "产品与游戏策划", r"游戏数值策划|数值策划|系统策划|游戏策划|产品策划"),
    ("T_F01_ACCOUNTING", "F01", "财务会计", r"结算专员|总账会计|成本会计|财务会计|税务会计"),
    ("T_F02_FINANCE", "F02", "融资与财富管理", r"融资经理|财富经理|投资经理|证券投资|信贷经理"),
    ("T_M02_HR", "M02", "人力资源", r"hr实习生|人事实习生|招聘实习生|人力资源实习生"),
    ("T_M03_ADMIN", "M03", "行政综合支持", r"部门助理|综合管理员|综合管理岗|行政助理|行政专员|经理助理"),
    ("T_S04_MEDIA", "S04", "媒体内容", r"^主播$|视频剪辑|内容编辑|新媒体编辑|责任编辑"),
    ("T_L03_LOGISTICS_SUPPORT", "L03", "后勤保洁", r"^清洁工$|^保洁员$|宿舍管理员"),
]


# 这类名称不能仅凭标题决定职业；它们进入职位描述证据阶段。
CONTEXT_TITLE_PATTERNS = [
    r"储备干部|管理培训生|管培生|实习生|应届毕业生",
    r"区域经理|城市经理|地区经理|大区经理|工程经理|工程主管|工程总监",
    r"测试工程师|测试技术员|测试员|试验工程师|试验员|安全工程师",
    r"技术员|技术工程师|工程师$|助理工程师|应用工程师|服务工程师|方案工程师|解决方案工程师",
    r"研发经理|研发总监|研究员|开发经理|开发工程师",
    r"产品开发工程师|产品研发工程师|产品设计工程师|产品工程师",
    r"策划经理|策划主管|策划专员|^策划$|推广专员|推广经理",
    r"计划员|计划工程师|计划主管|统计员|生产统计员",
    r"设计总监|设计经理|设计主管|视觉工程师|仿真工程师",
    r"售前经理|售前顾问|售前技术工程师|售前支持工程师|交付工程师|交付经理",
    r"操作员|值长|材料员|调度员|理货员|分拣员|跟单员",
]


def propose_title(title: str) -> dict[str, str]:
    for rule_id, code, family, pattern in TITLE_RULES:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return {
                "候选职业代码": code,
                "候选规则组": rule_id,
                "候选规则说明": family,
                "处理建议": "名称强规则候选",
            }
    for pattern in CONTEXT_TITLE_PATTERNS:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return {
                "候选职业代码": "",
                "候选规则组": "CONTEXT_REQUIRED",
                "候选规则说明": "名称存在歧义，必须结合职位描述",
                "处理建议": "进入描述证据规则",
            }
    return {
        "候选职业代码": "",
        "候选规则组": "UNRESOLVED_LONG_TAIL",
        "候选规则说明": "现有名称规则不足",
        "处理建议": "进入描述证据规则",
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    feature_root = Path(storage["features_root"]) / "occupation_v0.4.1"
    cleaned_root = Path(storage["curated_root"]) / "cleaned_v1"
    unions = []
    for year in range(2018, 2026):
        v4 = str(feature_root / f"jobs_{year}_occupation_v0.4.1.parquet").replace("\\", "/")
        cleaned = str(cleaned_root / f"jobs_{year}_cleaned.parquet").replace("\\", "/")
        unions.append(f"""
            SELECT {year} AS year,
                   v.source_record_id,
                   v.job_title_raw,
                   v.job_title_normalized,
                   v.occupation_status,
                   v.occupation_score_top1,
                   v.occupation_score_margin,
                   COALESCE(c.\"初级分类\", '') AS primary_category,
                   COALESCE(c.\"职位描述\", '') AS job_description
            FROM read_parquet('{v4}') v
            JOIN read_parquet('{cleaned}') c
              ON v.source_record_id = c.\"来源记录ID\"
            WHERE v.occupation_id = 'Z99'
        """)
    union_sql = " UNION ALL ".join(unions)
    connection = duckdb.connect()
    query = f"""
        WITH all_z99 AS ({union_sql}),
        title_counts AS (
            SELECT job_title_normalized,
                   COUNT(*) AS record_count,
                   COUNT(DISTINCT year) AS year_count,
                   MIN(year) AS first_year,
                   MAX(year) AS last_year,
                   MODE(occupation_status) AS main_status,
                   MAX(occupation_score_top1) AS max_fuzzy_score,
                   MAX(occupation_score_margin) AS max_fuzzy_margin,
                   MODE(NULLIF(TRIM(primary_category), '')) AS main_primary_category,
                   ARG_MAX(job_title_raw, LENGTH(job_description)) AS example_raw_title,
                   ARG_MAX(SUBSTR(job_description, 1, 600), LENGTH(job_description)) AS example_description
            FROM all_z99
            GROUP BY job_title_normalized
            ORDER BY record_count DESC
            LIMIT 5000
        )
        SELECT * FROM title_counts ORDER BY record_count DESC, job_title_normalized
    """
    candidates = connection.execute(query).fetchdf()
    proposals = pd.DataFrame([propose_title(str(title)) for title in candidates["job_title_normalized"]])
    candidates = pd.concat([candidates, proposals], axis=1)
    candidates.insert(0, "频次排名", range(1, len(candidates) + 1))
    candidates["全量覆盖率贡献"] = candidates["record_count"] / 5_235_398
    candidates["Z99内部占比"] = candidates["record_count"] / 1_496_331
    candidates["人工确认"] = ""
    candidates["人工修改职业代码"] = ""
    candidates["人工备注"] = ""
    candidates.to_csv(CANDIDATE_PATH, index=False, encoding="utf-8-sig")

    summary = (
        candidates.groupby(["候选规则组", "候选职业代码", "候选规则说明", "处理建议"], dropna=False)
        .agg(涉及标题数=("job_title_normalized", "size"), 预计命中记录数=("record_count", "sum"))
        .reset_index()
        .sort_values("预计命中记录数", ascending=False)
    )
    summary["对全样本覆盖率的潜在贡献"] = summary["预计命中记录数"] / 5_235_398
    summary["规则状态"] = "候选，尚未进入正式分类器"
    summary["人工意见"] = ""
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    context = candidates.loc[candidates["处理建议"].eq("进入描述证据规则")].copy()
    context = context.sort_values("record_count", ascending=False).head(1000)
    context.to_csv(CONTEXT_PATH, index=False, encoding="utf-8-sig")

    direct = int(candidates.loc[candidates["处理建议"].eq("名称强规则候选"), "record_count"].sum())
    description = int(candidates.loc[candidates["处理建议"].eq("进入描述证据规则"), "record_count"].sum())
    total = int(candidates["record_count"].sum())
    rules = json.loads(BASE_RULE_PATH.read_text(encoding="utf-8"))
    REPORT_PATH.write_text(f"""# occupation V4.2 规则候选诊断

## 结果

- 高频Z99标题：{len(candidates):,}种，覆盖{total:,}条记录；
- 名称强规则候选：预计覆盖{direct:,}条；
- 需要职位描述证据：{description:,}条；
- 正式职业口径仍为{len(rules['occupation_names']) - 1}类加Z99；
- 本轮只生成候选，没有覆盖V4.1或正式occupation_id。

## 下一步

1. 检查规则组汇总中的候选职业代码；
2. 对名称强规则抽样验证；
3. 为CONTEXT_REQUIRED和UNRESOLVED_LONG_TAIL建立职位描述证据词；
4. 在2022年试运行后再决定是否进入V4.2全量构建。
""", encoding="utf-8")
    print(f"TOP_TITLES={len(candidates)}")
    print(f"TOP_TITLES_RECORDS={total}")
    print(f"DIRECT_RULE_CANDIDATE_RECORDS={direct}")
    print(f"CONTEXT_RULE_RECORDS={description}")
    print(f"OUTPUT_DIR={OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
