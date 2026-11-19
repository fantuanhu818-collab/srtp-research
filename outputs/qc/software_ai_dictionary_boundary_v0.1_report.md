# 软件技能词典与AI词典边界检查v0.1

结论：`PASS`。

本检查只验证词典结构、词条归属和预设边界样例，不代替真实招聘数据试跑和人工准确性复核。

## 1. 输入

- 软件词典：`D:\SRTP科研\config\software_skill_rules_v0.1.csv`；
- 软件词典SHA256：`6448272c3b2ff367c736e08736e6e4a621c85ec1820f125bae0dd338e743ef12`；
- AI词典：`D:\SRTP中期\AI鎶€鑳借瘝鍏竉v1.0\ai_skill_dictionary_v1.0.json`；
- AI词典版本：`ai_skill_dict_v1.0_2026-11-18`；
- AI词典SHA256：`a3ee71d99f762a71117329928b30ebac509d35437da2ef3fefd312cbaa9a2792`；
- 边界测试：`D:\SRTP科研\config\software_ai_boundary_test_cases_v0.1.csv`。

## 2. 词典规模

- 软件规则：76条；
- 严格词规则：69条；
- 条件词规则：7条；
- AI词条：240条。

软件子类：

- `data_stats`：9条；
- `database`：13条；
- `devops`：9条；
- `engineering_design`：12条；
- `enterprise`：5条；
- `office_basic`：7条；
- `programming`：21条；

## 3. 检查结果

- 未解决词典冲突：0条；
- 边界测试：33条；
- 通过：33条；
- 失败：0条。

词典冲突明细见`outputs\qc\software_ai_dictionary_boundary_v0.1_conflicts.csv`，测试结果见`outputs\qc\software_ai_dictionary_boundary_v0.1_test_results.csv`。

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
