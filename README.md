# SRTP科研数据分析项目

本目录保存可以由Git管理的程序、研究规则、说明文档和小型结果。大型数据与答辩材料保存在`D:\SRTP`，不进入Git仓库。

## 目录

```text
code/       Stata与SQL程序
config/     路径示例和项目配置
docs/       工作流、分工和研究说明
outputs/    小型审计、表格和图形
scripts/    Python程序和运行工具
```

本机实际路径保存在`config/storage_paths.json`。该文件不会上传GitHub；其他电脑应复制`config/storage_paths.example.json`并填写自己的路径。

B及其Codex首次接手项目时，请先阅读`docs/agent交接.md`。

继续变量构建和基准回归数据准备时，请阅读`docs/数据分析线交接_2026-11-16.md`。

学习和审核回归代码时，请阅读`docs/AI技能工资溢价研究与Stata学习手册.md`。

构造正式分析变量前，请阅读精简后的`docs/变量构建清单与口径表_v0.2.md`；机器可读清单位于`config/variable_dictionary_v0.2.csv`。当前只建设13个基准核心变量，AI技能识别细则由AI技能工作线负责。

职业分类v0.1规则见`docs/occupation_id两层分类与关键词规则_v0.1.md`；职业大典小类v0.2试运行见`docs/occupation_id职业大典模糊匹配方案_v0.2.md`。基准回归采用“37个职业组为主、职业大典名称和模糊匹配辅助补漏”的v0.3方案，详见`docs/occupation_id粗分类与模糊匹配方案_v0.3.md`。v0.3已应用到2018—2025年全部5,235,398条回归底表记录，总覆盖率73.40%；人工复核入口为`outputs/occupation_review_20261117/occupation_manual_review_v0.3.xlsx`。

2022年职业分类试运行已经完成，结果仅用于修改规则，尚未进入正式回归数据。结论和问题见`outputs/qc/occupation_pilot_2022_report.md`。复现命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/12_pilot_occupation_2022.py

powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/13_validate_occupation_pilot_2022.py
```

职业大典代码表、别名表和2022年v0.2试运行可复现运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/14_prepare_occupation_dictionary_v02.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/15_pilot_occupation_dictionary_2022.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/16_validate_occupation_dictionary_pilot_2022.py
```

v0.2使用职业大典小类作为`occupation_id`。2022年扩展版覆盖174,033条（52.97%），其中高置信度45,938条（13.98%）；程序独立验证通过，人工准确率待复核。

v0.3的词典构建、2022年试跑和独立验证命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/17_prepare_occupation_anchor_dictionary_v03.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/18_pilot_occupation_coarse_2022.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/19_validate_occupation_coarse_2022.py
```

2018—2025年全量构建和独立验证命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/20_build_occupation_v03_all_years.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/21_validate_occupation_v03_all_years.py
```

全量职业特征位于`D:\SRTP\工作数据\features\occupation_v0.3`，按`source_record_id`与`confirmed_core_v2`逐年一一对应。构建报告和验证报告分别为`outputs/qc/occupation_v03_all_years_report.md`和`outputs/qc/occupation_v03_all_years_validation.md`。

## 数据审计与清洗交接

2018—2025年原始数据全量审计已于2026年11月15日完成。项目成员先阅读：

- `outputs/qc/full_audit/data_audit_report.md`：通俗版审计结论和术语说明；
- `outputs/qc/full_audit/cleaning_handoff.md`：下一步清洗程序的输入、输出和约束；
- `outputs/qc/full_audit/issue_register.csv`：每项问题的数量、影响、建议动作和决策责任人。
- `config/cleaning_rules.json`：已确认的23字段清单和第24列处理规则。

重新运行全量审计：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/01_audit_raw_data.py
```

运行成功时应同时出现`AUDIT_GATE=PASS`和`PYTHON_TASK=PASS`。

已确认标准化数据采用23个正式字段，第24个无名列不进入输出。运行字段结构标准化：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/03_standardize_23_fields.py
```

输出保存在`D:\SRTP\工作数据\curated\schema_23fields_v1`，大型Parquet不进入Git。年度记录数与字段检查结果保存在`outputs/qc/schema_23fields_summary.csv`。

问题切片和处理建议：

- `outputs/qc/full_audit/issue_examples_and_solutions.md`：三类问题的解释和清洗建议；
- `outputs/qc/full_audit/typical_issue_slices.csv`：19条可追溯的典型记录；
- `outputs/qc/full_audit/数据问题典型切片与处理建议.xlsx`：便于项目成员查看的本地Excel版本。

## 已确认的全量清洗规则与输出

项目组已确认：重复广告只保留一条；工资上下限和日期顺序颠倒时直接交换；结束日期或学历缺失时保留并标记；两个工资端点均无效时删除，只有一个有效端点时保留有效值。

运行全量清洗：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/04_clean_recruitment_data.py
```

独立复核：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/05_validate_cleaning.py
```

清洗数据保存在`D:\SRTP\工作数据\curated\cleaned_v1`。删除记录证据保存在`D:\SRTP\工作数据\evidence\cleaning_v1\deleted_records.parquet`。年度统计、规则表、前后对照切片和验证说明位于`outputs/qc/cleaning_v1_*`；便于组内查看的Excel为`outputs/qc/cleaning_v1_report.xlsx`。

## 已确认核心变量构造

第一版五个变量仍可复现：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/08_build_confirmed_core_variables.py

powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/09_validate_confirmed_core_variables.py
```

第一版输出保存在`D:\SRTP\工作数据\features\confirmed_core_v1`，保持只读。

项目组进一步确认学历处理、上市公司集团层级`firm_id`和保守城市标准化后，运行v2：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/10_build_confirmed_core_v2.py

powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/11_validate_confirmed_core_v2.py
```

v2输出保存在`D:\SRTP\工作数据\features\confirmed_core_v2`，共5,235,398条，已经独立复核。它包含`wage_mid`、`ln_wage`、`education`、`experience`、初版`firm_id`、初版`city_id`和`year_month`。企业与城市口径仍是不完善的中期初版，限制见`outputs/qc/confirmed_core_v2_validation.md`。非AI技能中的认知和社交技能已完成2022年候选试运行并通过结构验证，待240条人工复核；软件技能尚未构建。v0.3候选`occupation_id`已全量构建并独立验证，待人工准确性复核后冻结。

## 非AI技能2022年试运行

方法见`docs/非AI技能变量构建方法.md`。当前只试跑`skill_cognitive`和`skill_social`，不依赖尚未完成的AI词典：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/22_pilot_non_ai_cognitive_social_2022.py

powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/23_validate_non_ai_cognitive_social_2022.py
```

2022年328,548条中，认知技能候选命中70,532条（21.47%），社交技能候选命中167,487条（50.98%）；结构验证通过。候选特征位于`D:\SRTP\工作数据\features\non_ai_skills_pilot_v0.1`，人工复核前不能作为正式冻结变量。

## 已确认工资修正（wage_fix_v1）

`cleaned_v1`的工资规则只处理非数值、≤0、上下限颠倒和单端缺失，不检查单位。已证实的成批单位错误有三处：2018年平台11（月薪≥3万实际是年薪）、2021年平台72（≥6万是年薪）、2018—2019年平台64（整平台约放大10倍）。修正结果保存在`D:\SRTP\工作数据\features\wage_fix_v1`，共修正135,930条，其余记录原值不动。字段`wage_mid_orig`保留原值、`wage_mid_fixed`为修正值、`wage_fix_flag`标记是否修正，按`source_record_id`与`confirmed_core_v2`一一连接。

- 规则：`config/wage_fix_rules_v1.json`
- 构建：`code/python/40_build_wage_fix_v1.py`；独立复核：`code/python/41_validate_wage_fix_v1.py`；完整性扫描：`code/python/42_scan_wage_anomalies.py`
- 说明：`docs/工资极端值修正_wage_fix_v1_2026-11-19.md`
- 复核报告：`outputs/qc/wage_fix_v1_validation.md`

`cleaned_v1`和`confirmed_core_v2`均未改动。


## 运行Python

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath scripts/任务名称.py
```

## 运行Stata

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_stata_task.ps1 `
  -DoFile code/stata/任务名称.do `
  -ExpectedLog outputs/analysis/任务名称.log
```

原始数据只能读取，不得由程序修改、移动、重命名或覆盖。
