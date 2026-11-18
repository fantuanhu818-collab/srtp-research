# occupation V4.2 2022年候选试运行报告

## 核心结果

- 2022年总记录：328,548条；
- V4.1已分类：239,554条，覆盖率72.91%；
- V4.2本轮仅从Z99新增：12,165条；
- V4.2候选版已分类：251,719条，覆盖率76.62%；
- 仍为Z99：76,829条；
- 新增分类全部标记为需要人工抽样复核，尚未作为正式回归数据。

## 安全边界

1. V4.1中已分类的记录一条也不改；
2. “初级分类”最多加1分，只能确认，不能单独决定；
3. 接受条件为总分至少5分、领先第二名至少2分，并且有标题强证据或至少两项独立的职位描述强证据；
4. 400条分层样本复核准确率达到90%后，才能讨论全量运行。

## 文件

- 候选特征表：`D:\SRTP\工作数据\features\occupation_v0.4.2_candidate\jobs_2022_occupation_v0.4.2_candidate.parquet`
- 全部Z99证据审计：`D:\SRTP科研\outputs\occupation_v042_rule_development_20261118\occupation_v042_2022_z99_evidence_audit.csv`
- 400条人工复核样本：`D:\SRTP科研\outputs\occupation_v042_rule_development_20261118\occupation_v042_2022_manual_review_sample_400.csv`
