# Alekseeva et al.（2021）如何处理AI技能与一般软件技能重合

更新日期：2026-11-17
用途：为本项目`ai_skill`与非AI技能变量的构造、基准回归和稳健性检验提供一手文献依据。

## 1. 一句话结论

Alekseeva et al.（2021）没有要求AI技能与软件技能在招聘广告层面互斥，也没有删除同时要求两类技能的广告。论文采用的是：**词条层面分开分类、广告层面允许同时命中；回归中同时控制AI和其他技能；再用软件技能样本限制及AI×软件交互检验重合问题。**

这意味着本项目不应强行让`ai_skill`与`skill_software`二选一。更合适的做法是把AI专属术语与一般软件术语分开，但允许一条广告同时取1，然后用分步回归、软件技能子样本和交互项说明两者的关系。

## 2. 论文原文采用的变量口径

### 2.1 AI技能

论文根据Burning Glass Technologies（BGT）的技能分类体系识别AI招聘广告。BGT把约17,000项技能划入不重叠的技能类别；AI词包括AI方法、任务和专用软件包，例如artificial intelligence、machine vision、deep learning、image processing、speech recognition、IBM Watson、TensorFlow、Random Forests等。招聘广告要求至少一项AI技能时，`AI=1`。见作者稿第7—8页、附录表A1第44—45页。

附录表A1列出71项AI技能。值得注意的是，论文将TensorFlow、Keras、OpenCV、Random Forests等AI专用工具归入AI技能；Python、SQL等通用编程或数据库技能没有因为常用于AI就自动列入AI技能。[期刊正式页面](https://doi.org/10.1016/j.labeco.2021.102002)；[作者SSRN稿及下载入口](https://papers.ssrn.com/abstract=3470610)。

### 2.2 非AI技能

论文使用10个非AI技能组作为工资回归控制变量：Software、Computer、Cognitive、Social、Character、Writing、Customer Service、Project Management、People Management、Finance and Accounting。分类沿用Deming and Kahn（2018）及Deming and Noray（2019）的定义。作者特别说明，Software是BGT同时标记为“software skills”和“specialized skills”的技能；Cognitive包含描述中带有solving、research、decision、thinking等含义的技能。见作者稿第8—9页、脚注4和第18页脚注11。

论文中的“类别不重叠”是指**同一个技能词条在BGT技能本体中的归类**，不是指一条广告只能要求一类技能。一条广告可以同时要求AI、Software、Cognitive和Social技能。

## 3. 论文如何正面处理AI与软件技能重合

### 3.1 先描述重合，而不是回避重合

表1 Panel B显示，在AI招聘广告中，Software技能出现频率约为全样本平均值的4倍，Cognitive技能约为全样本平均值的2.5倍。作者据此明确承认AI与软件、认知技能经常共同出现，而不是把共现视为数据错误。见作者稿第9页、表1 Panel B。

### 3.2 工资回归同时放入AI和其他技能

论文第4节的式（7）为：

```text
log(wage) = β1 AI + β2 Other Skills + firm FE
            + occupation×local-market FE + year-month FE + error
```

其中`Other Skills`是10个非AI技能虚拟变量。表3的所有列都同时估计AI、Software、Cognitive、Social等技能的系数，而不是先把“软件岗位”从AI岗位中删除。见作者稿第18—19页、式（7）；表3位于作者稿第38—39页。

表3中，在加入企业固定效应、6位SOC职业×CBSA地区固定效应和年月固定效应后，AI系数为0.107，Software系数为0.0595，Cognitive系数为0.0341，Social系数为0.0210。加入岗位名称固定效应后，AI系数降为0.0514，Software系数降为0.0302。作者把系数下降解释为：AI要求经常与其他高工资、但未被完全观察到的技能要求共同出现。见表3及正文第18—19页。

### 3.3 在软件技能广告内部重新比较

作者担心：如果广告没有把实际需要的软件或认知技能完整写出，AI系数可能被高估。因此正文第20—21页增加了检验：在AI与软件技能共同出现的相关样本中重新估计，结果与基准结果相近。

从识别逻辑看，这项检验的核心是比较“AI＋一般软件技能”与“一般软件技能但没有AI”的广告，从而减少普通软件岗位工资较高造成的混淆。原文对此检验只做文字报告，没有单独列表。

### 3.4 加入技能交互项

附录表A6在基准回归中分别加入：

- `AI × Software`；
- `AI × Computer`；
- `AI × Cognitive`；
- 以及三个交互项同时加入。

交互项均不显著；`AI × Software`估计值约0.024—0.027。加入该交互后，AI主效应从约0.107降至0.0866，作者据此认为较高的AI工资差异主要来自同时写明AI和软件要求的岗位，但没有证据表明两者存在统计上显著的额外互补溢价。见正文第20—21页与附录表A6第50—51页。

### 3.5 使用更窄的职业样本和更细固定效应

论文还做了两类相关检验：

1. 附录表A4只保留专业职业（2位SOC 11—29和41—43），结果定性不变；
2. 表3逐步加入企业固定效应、6位SOC×地区固定效应和岗位名称固定效应。岗位名称固定效应加入后AI系数明显下降，但仍为正。

这表明论文不依赖词典在文本层面“完全切开”AI和软件技能，而是利用同企业、同职业—地区、甚至同岗位名称内部的比较提高可比性。

## 4. 对本项目最直接的启示

### 4.1 词条层面分开，广告层面允许重合

建议将词典分成两套：

- `ai_skill`：机器学习、深度学习、NLP、计算机视觉、神经网络、TensorFlow、PyTorch、LLM、RAG等AI专属概念、方法和工具；
- `skill_software`：Python、Java、C++、SQL、数据库、Linux、Git、Docker、Excel、CAD、SAP、ERP等通用编程、软件和数字工具。

AI专属词不要重复放入一般软件词典；但一条广告如果同时写“Python＋机器学习”，应同时得到`ai_skill=1`和`skill_software=1`。这正是论文的处理逻辑。

### 4.2 中期最小技能组

论文使用10个非AI技能组，但本项目不必在中期机械复制10个变量。结合研究问题与工作量，至少保留：

1. `skill_software`：一般软件和数字工具；
2. `skill_cognitive`：分析、研究、决策、思考、问题解决；
3. `skill_social`：沟通、团队协作、谈判、表达。

这三类正是AI广告最容易同时要求、也最可能混入AI工资系数的技能。若中期时间允许，最值得增加的第四类是合并后的`skill_management`（项目管理＋人员管理），因为论文表3显示这两类技能的工资系数较大，正文也指出其工资差异最接近AI技能。

### 4.3 建议的基准与稳健性回归

主规格可对应论文式（7）：

```stata
reghdfe ln_wage ai_skill skill_software skill_cognitive skill_social ///
    education experience i.source, ///
    absorb(firm_id occupation_id#city_id year_month) vce(cluster firm_id)
```

建议同时报告以下递进结果：

1. 不加入非AI技能，观察AI岗位整体工资差异；
2. 加入认知和社交技能；
3. 再加入一般软件技能，作为对AI专属技能差异的更严格估计；
4. 只在`skill_software=1`的广告中重新估计`ai_skill`；
5. 加入`ai_skill × skill_software`；
6. 在数字技术和专业技术职业组中重复估计；
7. 若能构造稳定的高频标准化岗位名称，在该子样本中加入岗位名称固定效应作为后期稳健性检验。

本项目的`occupation_id`只有37组，比论文6位SOC更粗，因此“同职业内部”仍可能存在较大岗位差异。软件技能子样本、交互项以及高频标准化岗位名称固定效应，对本项目比对论文更重要。

### 4.4 必须先做的描述性检查

在回归前应报告：

- `P(skill_software=1 | ai_skill=1)`；
- `P(skill_software=1 | ai_skill=0)`；
- AI与软件、认知、社交技能的2×2交叉表；
- 各组合的工资均值、中位数和样本量；
- 三类非AI技能在不同职业和年份中的出现率。

这对应论文表1 Panel B的思路，能够直接展示重合程度，而不是只在回归中隐含处理。

### 4.5 技能总数只能做稳健性控制

论文后续用广告要求的技能总数控制职位描述或技能要求长度，但作者明确警告：如果AI采用本身导致岗位要求更多技能，控制技能总数会部分消除AI的真实关联。因此，本项目可以把文本长度或技能总数放在稳健性检验中，不能作为唯一基准规格。见正文第23—24页、附录表A10。

## 5. 与论文不能直接等同的地方

1. 论文使用BGT已经清洗并分类的结构化技能字段；本项目使用中文原始职位描述，必须增加短语边界、否定词、公司宣传段落排除和人工验证。
2. 论文的技能词条本体不重叠；本项目需自行建立机器可读的词典归属表，并规定每个词的主类别。
3. 论文有6位SOC和岗位名称固定效应；本项目当前只有37组`occupation_id`，分类更粗。
4. 因此，不能直接套用论文的系数解释，也不能声称三个非AI技能已经吸收全部岗位复杂度。

## 6. 推荐决策

采用“论文式处理”而不是试图让AI与软件广告互斥：

- 保留`ai_skill`、`skill_software`、`skill_cognitive`、`skill_social`；
- AI专属词与一般软件词在词典层面互斥；
- 招聘广告层面允许多个技能变量同时为1；
- 主回归同时控制三类非AI技能；
- 额外报告不控制软件、软件岗位子样本和`AI×Software`交互结果；
- 若只增加一个新的非AI技能类别，优先增加`skill_management`，但不必在中期复制全部10类。

## 一手来源

- Alekseeva, L., Azar, J., Giné, M., Samila, S., & Taska, B. (2021). *The Demand for AI Skills in the Labor Market*. **Labour Economics, 71**, 102002. [期刊DOI与正式页面](https://doi.org/10.1016/j.labeco.2021.102002)。
- 作者公开工作稿（最后修订于2021-05-10，包含正文、表格与附录）：[SSRN摘要及下载入口](https://papers.ssrn.com/abstract=3470610)。本文中的页码均以该60页作者稿的印刷页码为准。
