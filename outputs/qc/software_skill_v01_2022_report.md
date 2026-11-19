# 2022年软件技能变量试运行报告

结论：程序已按软件技能词典v0.1完成2022年候选变量构建。结果仅用于诊断和人工复核，在人工验证前不能称为正式变量。

## 1. 样本和文本

- 回归底表记录：328,548条；
- 文本可用于判断：328,402条（99.96%）；
- 文本不可判断：146条（0.04%）。

## 2. 初步识别结果

- `skill_software = 1`：103,618条（31.54%）；
- 命中基础办公软件：59,303条（18.05%）；
- 命中专业软件：60,410条（18.39%）；
- 仅基础办公软件：43,208条（13.15%）；
- 仅专业软件：44,315条（13.49%）；
- 两类均命中：16,095条（4.90%）；
- 存在条件词命中：54,882条（16.70%）；
- 岗位名称存在明确软件词：4,985条（1.52%）。

以上比例是词典规则产生的候选覆盖，不等于人工确认后的真实软件技能需求比例。基础办公软件按照项目组确认口径进入主变量，但单独保留子类供检查和后续稳健性分析。

## 3. 处理口径

- 岗位名称中的明确软件名称可以命中，宽泛名称不能单独命中；
- Office、Word、Excel、PowerPoint和WPS计入软件技能；
- TensorFlow、PyTorch、Keras、OpenCV等AI专属工具不进入软件词典；
- 复用AI v1.0的分句、公司介绍和否定表达口径；
- 保存全部规则ID，并将逐次命中证据另存为稀疏证据表。

## 4. 试跑中发现并修正的问题

- 为UG增加英文边界，避免误命中UGC、bug和Debug；最终命中2,046条；
- 删除歧义极大的裸GCP，只保留Google Cloud Platform和中文云平台名称；云平台规则最终命中743条；
- 将裸R限制在明确技能要求或技能列表中，排除邮箱字符和GR&R；R语言规则最终命中321条；
- 补充Photoshop、Illustrator、Premiere、After Effects等设计软件，最终命中2,844条；
- “办公软件技能”条件规则命中36,735条，是当前最高频规则，必须作为人工复核重点。

## 5. 输出

- 候选特征：`D:\SRTP\工作数据\features\software_skill_pilot_v0.1\jobs_2022_software_skill_v0.1.parquet`；
- 稀疏证据：`D:\SRTP\工作数据\evidence\software_skill_pilot_v0.1\software_skill_hits_2022_v0.1.parquet`；
- 汇总：`outputs\qc\software_skill_v01_2022_summary.csv`；
- 规则命中：`outputs\qc\software_skill_v01_2022_rule_counts.csv`；
- 子类分布：`outputs\qc\software_skill_v01_2022_subgroup_distribution.csv`；
- 平台分布：`outputs\qc\software_skill_v01_2022_platform_distribution.csv`；
- 职业分布：`outputs\qc\software_skill_v01_2022_occupation_distribution.csv`；
- 规则例子：`outputs\qc\software_skill_v01_2022_rule_examples.csv`；
- 诊断复核样本：`outputs\qc\software_skill_v01_2022_review_sample.csv`。

## 6. 下一步

1. 检查高频词、基础办公软件占比和典型切片；
2. 修正明显误判后，与认知、社交候选结果生成统一人工复核工作簿；
3. 人工验证完成后再运行2018—2025年全样本。
