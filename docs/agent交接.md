# SRTP科研项目交接说明

更新日期：2026-11-16

当前仓库：`D:\SRTP科研`

GitHub：`https://github.com/fantuanhu818-collab/srtp-research`

数据清洗基线提交：`fe47e6d`（`feat: implement full recruitment data cleaning`）

本文档是新会话和新协作者的首要入口。接手者应先阅读本文件，再阅读`README.md`和`docs/目前进度.md`。除非研究组修改清洗规则，否则不要重新做已经完成并验收的数据审计和`cleaned_v1`。

> 数据分析线的最新变量构建状态和待确认口径见`docs/数据分析线交接_2026-11-16.md`。继续基准回归数据准备前，应先阅读该文件。

## 1. 给新会话的直接指令

可以把下面这段话直接发给同一项目中的新Codex会话：

> 请接手`D:\SRTP科研`中的SRTP经济学科研项目。先完整阅读`docs/agent交接.md`、`README.md`、`docs/目前进度.md`和`config/cleaning_rules.json`，再检查Git状态及`outputs/qc/cleaning_v1_summary.csv`。当前全量审计、23字段标准化和cleaned_v1清洗已经完成并验收，不要擅自重做或覆盖。请先用通俗语言说明研究目标、现有数据层级、已经确认的规则、可直接使用的字段、尚未完成的变量和下一步计划，再执行新的任务。

## 2. 研究目标与解释边界

项目使用2018—2025年中国网络招聘数据，研究岗位要求AI技能时，招聘工资是否更高，以及这种关系在不同年份、职业、行业和地区是否存在差异。

当前研究只能解释为相关关系。因果识别方案尚未确定，不得把回归结果直接写成“AI技能导致工资提高”。

## 3. 当前阶段

已经完成：

1. 2018—2025年原始数据全量审计；
2. 正式字段统一为23个，第24个无名字段从标准化数据中删除；
3. 生成23字段标准化Parquet；
4. 按项目组确认的工资、日期、重复和缺失规则完成全量清洗；
5. 生成逐条来源ID、清洗标记、原始值和删除证据；
6. 独立读取清洗结果并完成质量复核；
7. 代码、小型统计和说明文档已推送GitHub。

当前下一阶段：

```text
cleaned_v1稳定基础数据
→ 构造AI技能、学历、地区、行业等特征
→ 合并形成analysis_v1正式分析数据
→ 描述统计
→ 基准回归和扩展分析
```

`cleaned_v1`是后续变量构造的共同基础，不应直接覆盖。新变量应写入特征数据或新的分析数据版本。

## 4. 数据层级和实际位置

### 4.1 原始数据

- 路径：`D:\SRTP\分年份保存数据`
- 规则：严格只读，不得修改、移动、重命名或覆盖。
- 内容：2018—2025年原始CSV及对应资料。

### 4.2 23字段标准化数据

- 路径：`D:\SRTP\工作数据\curated\schema_23fields_v1`
- 大小：约2.12 GiB。
- 作用：只统一字段结构，不处理记录内容问题。
- 记录数：6,050,088条。

### 4.3 当前清洗基础数据

- 路径：`D:\SRTP\工作数据\curated\cleaned_v1`
- 大小：约1.63 GiB，共8个年度Parquet和1个清单文件。
- 记录数：5,235,461条。
- 作用：后续所有特征构造和正式分析的基础。

### 4.4 删除记录证据

- 路径：`D:\SRTP\工作数据\evidence\cleaning_v1\deleted_records.parquet`
- 大小：约15 MB。
- 内容：被删除记录的`来源记录ID`、删除原因、重复组信息等。

### 4.5 GitHub中的内容

GitHub只保存代码、规则、文档和小型统计结果，不保存原始数据、标准化Parquet或清洗Parquet。仓库当前跟踪内容约4.34 MiB，未跟踪任何`.parquet`文件。

其他电脑克隆GitHub仓库后不会自动获得数据，需要单独传输数据文件，并根据`config/storage_paths.example.json`建立本机的`config/storage_paths.json`。

## 5. 已确认并执行的清洗规则

正式规则保存在`config/cleaning_rules.json`。

### 5.1 字段结构

- 只保留23个正式字段；
- 删除第24个无名字段；
- 原始CSV和审计证据保持不变。

### 5.2 重复广告

重复键由以下字段构成：企业名称、招聘岗位、工作城市、招聘发布日期、职位描述。

重复广告只保留一条。选择顺序为：有效工资端点更多、学历非缺失、结束日期非缺失、整体字段更完整、来源记录ID更小。

### 5.3 工资

- 工资端点必须能转为数值且大于0，才视为有效；
- 最低月薪和最高月薪都无效：删除整条记录；
- 只有一个端点有效：保留有效值，另一个端点设为缺失；
- 两个端点有效但上下限颠倒：交换上下限；
- `月薪代表值`：两个端点有效时取均值，只有一个有效时取该值。

尚未执行工资缩尾、异常高值删除、对数变换或实际工资折算。这些属于分析设定，必须单独讨论并保留版本。

### 5.4 日期

- 招聘结束日期早于发布日期：交换两个日期；
- 招聘结束日期缺失：保留记录并标记缺失；
- 日期交换后同步更新相应年份字段。

### 5.5 学历

- 学历要求缺失：保留记录并标记缺失；
- 尚未把学历文本统一编码为“不限、专科、本科、硕士、博士”等控制变量。

## 6. 清洗结果

| 指标 | 数量 |
|---|---:|
| 输入记录 | 6,050,088 |
| 删除：两个工资端点均无效 | 489,637 |
| 删除：重复广告 | 324,990 |
| 清洗后保留 | 5,235,461 |
| 工资上下限交换 | 174 |
| 日期顺序交换 | 12 |
| 只有一个工资端点有效并保留 | 97,107 |
| 学历缺失但保留 | 31,887 |
| 结束日期缺失但保留 | 1,480,268 |

独立复核结果：重复`内容ID`、双端点无效工资、工资上下限颠倒、日期颠倒、缺失标记不一致和无效`月薪代表值`均为0。

## 7. cleaned_v1字段说明

每个年度清洗文件包含23个正式字段和14个交接字段，共37列。

### 7.1 后续分析优先使用

- `来源记录ID`：每条来源记录的稳定标识，构造招聘记录层面的变量时用它一对一连接；
- `内容ID`：重复广告的内容标识，cleaned_v1中保持唯一；
- `月薪代表值`：后续工资分析的基础工资变量；
- `职位描述`：AI技能识别的核心文本；
- `学历要求`、`工作城市`、`上市公司行业`、`招聘发布年份`：后续控制变量的基础字段。

### 7.2 清洗追溯字段

- `工资清洗方式`；
- `工资上下限已交换`；
- `日期顺序已交换`；
- `学历要求缺失`；
- `招聘结束日期缺失`；
- `重复组记录数`；
- `最低月薪_原始`、`最高月薪_原始`；
- `招聘发布日期_原始`、`招聘结束日期_原始`；
- `学历要求_原始`。

清洗后的正式字段不要再与`_原始`字段混用。`_原始`字段只用于追溯和敏感性检查。

## 8. 程序和运行顺序

项目Python环境位于仓库的`.venv`，推荐统一通过PowerShell包装脚本运行。

### 8.1 全量审计

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/01_audit_raw_data.py
```

### 8.2 生成23字段标准化数据

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/03_standardize_23_fields.py
```

### 8.3 生成cleaned_v1

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/04_clean_recruitment_data.py
```

### 8.4 独立复核

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/05_validate_cleaning.py
```

成功时必须同时出现`INDEPENDENT_CLEANING_VALIDATION=PASS`和`PYTHON_TASK=PASS`。

### 8.5 导出典型切片

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath code/python/06_export_cleaning_examples.py
```

Excel汇总由`code/javascript/07_create_cleaning_workbook.mjs`生成。主要交付物为本机的`outputs/qc/cleaning_v1_report.xlsx`，Excel按仓库规则不上传GitHub。

## 9. 关键文档和小型结果

接手时优先阅读：

1. `README.md`：仓库入口和运行命令；
2. `docs/目前进度.md`：阶段状态；
3. `config/cleaning_rules.json`：机器可读的最终清洗规则；
4. `outputs/qc/full_audit/data_audit_report.md`：通俗版数据审计；
5. `outputs/qc/full_audit/cleaning_handoff.md`：审计到清洗的原交接；
6. `outputs/qc/cleaning_v1_summary.csv`：年度清洗统计；
7. `outputs/qc/cleaning_v1_validation.md`：清洗验收和字段使用说明；
8. `outputs/qc/cleaning_v1_examples.csv`：7类处理动作的前后对照切片；
9. `outputs/qc/cleaning_v1_report.xlsx`：本机易读版Excel汇总。

## 10. 下一步工作建议

### 10.1 特征层

不要修改`cleaned_v1`。建议在`D:\SRTP\工作数据\features`中分别保存：

- AI技能变量：按`来源记录ID`一对一连接；
- 学历分类变量：由`学历要求`文本统一编码；
- 地区控制变量：先规范城市，再按“城市—年份”连接外部数据；
- 行业变量：由现有行业字段规范化，必要时建立行业映射表；
- 其他招聘记录层面的控制变量。

每类特征应有独立版本、生成程序、规则文件和质量检查，不要把所有处理塞进一个不可追溯的脚本。

### 10.2 正式分析数据

建议在`D:\SRTP\工作数据\analysis\analysis_v1`生成新的分析数据集：

```text
cleaned_v1
+ AI技能特征
+ 学历控制变量
+ 地区—年份控制变量
+ 行业、年份和其他控制变量
= analysis_v1
```

`analysis_v1`仍须保留`来源记录ID`。合并后必须检查一对一或多对一关系、记录数守恒和变量缺失率。

### 10.3 当前尚未决定的问题

- AI技能词典、传统AI与生成式AI分类及人工标注方案；
- 学历文本的统一分类规则；
- 城市名称规范化和地区外部数据来源；
- 工资缩尾、对数变换、通胀调整和极端值处理；
- 企业名称与股票代码多对多问题的分析层级；
- 正式回归的样本限制、固定效应和标准误聚类层级；
- 因果识别策略。

这些问题会影响研究结论。新会话应先列出证据和可选方案，由项目成员确认后再落地，不应自行把一种方法当作最终设定。

## 11. Git协作状态和规则

- 当前分支：`main`；
- 数据清洗基线提交：`fe47e6d8b728b44cc4f8997bb6a987d0143d37e8`；
- 远端：`origin` → `https://github.com/fantuanhu818-collab/srtp-research.git`；
- 大型数据和本机路径配置由`.gitignore`排除。

开始工作前运行：

```powershell
git status
git pull --ff-only origin main
```

完成一项可独立检查的工作后：实际运行程序，检查记录数、合并关系、缺失率和异常，更新`docs/目前进度.md`和本交接文档，只提交代码、规则、文档和小型结果。不要提交原始数据、DTA、Parquet、DuckDB、日志、临时文件或本机路径配置。

## 12. 接手后的第一轮检查

1. 阅读本文件、`README.md`、`docs/目前进度.md`和`config/cleaning_rules.json`；
2. 运行`git status`，确认没有未知的用户修改；
3. 检查`config/storage_paths.json`指向的目录是否存在；
4. 检查`D:\SRTP\工作数据\curated\cleaned_v1\cleaning_manifest.json`；
5. 如需使用数据，先运行`code/python/05_validate_cleaning.py`，不要直接重跑全量清洗；
6. 说明本次任务将读取什么、生成什么、是否改变既有数据；
7. 完成后保存可重复运行的程序和质量检查结果。

交接完成的标准不是“知道文件在哪里”，而是能够从`cleaned_v1`稳定地继续构造特征和分析数据，同时保持原始数据、清洗规则和每次变量构造都可追溯。
