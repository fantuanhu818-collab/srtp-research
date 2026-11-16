# AI技能识别方案与人工标注规则 v0.1

更新日期：2026-11-16　负责人：B（李宇白）　复核人：A（胡嘉琪）

状态：**草案**。词典和程序已能运行，但尚未用真实广告做人工标注验证，结果不得写成正式结论。

## 一、要识别什么

`ai_skill = 1`：招聘广告**明确要求应聘者具备或使用AI技能**。

它不等于：

- 企业是AI公司，或企业产品用到AI（公司介绍、产品介绍不算）；
- 岗位属于AI行业，但岗位本身不要求AI技能（如AI公司的销售、会计）；
- 广告中出现了“AI”字样（可能是Adobe Illustrator、简历CV、人名等）。

## 二、三层词典

词典文件：`config/ai_skill_dictionary_v0.1.json`，Python可直接读取，规则版本写在`rule_version`字段。

|层级|含义|例子|进入哪个变量|
|---|---|---|---|
|严格词 strict|含义基本唯一的AI技术词|机器学习、深度学习、NLP、PyTorch、大模型、ChatGPT、AIGC、RAG、提示词|`ai_skill`和`ai_skill_broad`|
|宽泛词 broad|和AI相关但容易误判|人工智能、AI、ML、CV、数据挖掘、自动驾驶、AI工具|只进`ai_skill_broad`|
|复核词 review|AI相邻、是否算AI技能有争议|数据标注、AI训练师、算法工程师、智能制造|只做标记`ai_review_flag`，用于抽样|

严格词再分为两类，对应中期检查表中“传统AI与生成式AI”的区分：

- **传统AI**（`ai_traditional`）：Acemoglu等（2022）清单词及同类补充，如机器学习、深度学习、神经网络、NLP、计算机视觉、语音识别、推荐算法、TensorFlow/PyTorch等；
- **生成式AI**（`ai_genai`）：大模型/LLM、ChatGPT/GPT、文心一言等国产大模型、AIGC、Midjourney/Stable Diffusion、提示词、RAG、LangChain、智能体、模型微调等。

基准回归使用`ai_skill`（严格版）；`ai_skill_broad`留作稳健性检验，与Acemoglu等（2022）“narrow为主、broad为稳健性”的做法一致。

### 2.1 词从哪里来

严格词的基础清单来自 **Acemoglu, Autor, Hazell & Restrepo (2022)**, “Artificial Intelligence and Jobs: Evidence from Online Vacancies”, *Journal of Labor Economics* 40(S1): S293–S340。该文用Burning Glass招聘数据构造两种AI岗位口径：

- **narrow AI**：脚注13（p. S305）列出的33项AI技能，作为主口径；
- **broad AI**：机器学习、人工智能、自然语言处理和数据科学四个技能簇的全部技能；作者认为它可能混入一般IT职能，只用于附录稳健性检验。

本项目对应关系：narrow清单逐项翻译 → 严格词基础；broad技能簇 → 宽泛词；再加两类项目补充。词典中每个词条都有`source`字段标明来源，清单词另有`source_skill`记录英文原文。

|来源标记|含义|词条数|
|---|---|---:|
|`AAHR2022_narrow`|33项narrow AI技能的翻译|33|
|`AAHR2022_broad_cluster`|broad口径技能簇对应的宽泛词|5|
|`project_extension`|与清单同类的方法和框架（如清单有Keras、XGBoost，补充PyTorch、LightGBM）、中文常见写法和易误判词|15|
|`project_genai`|2022年11月ChatGPT发布后的生成式AI词；原清单基于2010—2018年美国数据，没有这类词|20|

说明：Alekseeva等（2021）同样用Burning Glass技能识别AI岗位并估计工资溢价，是本项目最接近的实证范例；但其技能清单在付费全文中，尚未核对，因此词典基础暂以可公开核对的Acemoglu等（2022）清单为准。拿到Alekseeva等原文后应比对两份清单，并在论文中说明差异。

### 2.2 清单翻译表

|序号|原文技能|中文匹配写法|层级|说明|
|---:|---|---|---|---|
|1|machine learning|机器学习|严格||
|2|computer vision|计算机视觉|严格||
|3|machine vision|机器视觉|严格|中文工业检测岗常用，人工标注重点核查|
|4|deep learning|深度学习|严格||
|5|virtual agents|虚拟助手、智能助理、虚拟代理|严格||
|6|image recognition|图像识别、图片识别|严格||
|7|natural language processing|自然语言处理、自然语言理解|严格||
|8|speech recognition|语音识别|严格||
|9|pattern recognition|模式识别|严格||
|10|object recognition|物体识别、目标识别|严格||
|11|neural networks|神经网络|严格||
|12|AI chatbot|聊天机器人、对话机器人、问答机器人|严格||
|13|supervised learning|监督学习|严格|也匹配半监督学习|
|14|text mining|文本挖掘|严格||
|15|unsupervised learning|无监督学习|严格||
|16|image processing|数字图像处理、图像处理算法|严格|中文“图像处理”常指PS修图，只取“数字图像处理/图像处理算法”；单独“图像处理”放入broad|
|17|Mahout|（保留英文）|严格||
|18|recommender systems|推荐系统、推荐算法、个性化推荐|严格||
|19|support vector machines|支持向量机|严格||
|20|random forests|随机森林|严格||
|21|latent semantic analysis|潜在语义分析|严格||
|22|sentiment analysis/opinion mining|情感分析、观点挖掘、意见挖掘|严格||
|23|latent Dirichlet allocation|潜在狄利克雷分配、LDA主题模型|严格||
|24|kernel methods|核方法|严格||
|25|Keras|（保留英文）|严格||
|26|gradient boosting|梯度提升|严格||
|27|OpenCV|（保留英文）|严格||
|28|XGBoost|（保留英文）|严格||
|29|Libsvm|（保留英文）|严格||
|30|Word2vec|词向量|严格||
|31|machine translation|机器翻译|严格||
|32|sentiment classification|情感分类|严格||
|33|predictive models|预测模型|宽泛|清单内词，但中文“预测模型”常指一般统计/财务预测，降为broad|

翻译时的取舍（论文方法部分需说明）：

- **predictive models（预测模型）降为宽泛词**：中文“预测模型”常见于财务、销售预测，不一定是AI；
- **image processing只取“数字图像处理/图像处理算法”**：中文“图像处理”在设计岗常指PS修图，单独出现时放入宽泛词，并在与PS、修图同句时排除；
- **sentiment analysis排除婚恋咨询语境**：中文“情感分析师”多为情感咨询岗位；
- **machine vision保留为严格词**：与原文一致，但中文工业检测岗位大量使用，人工标注时重点核查。


## 三、判断步骤

程序：`code/python/ai_skill_matcher.py`（规则）、`code/python/12_build_ai_skill.py`（全量运行和抽样）。

1. **读取文本**：`招聘岗位`和`职位描述`，按`来源记录ID`一一对应。
2. **切句并识别段落**：按句号、分号、换行和“1、2、”等编号切句。遇到“公司简介/关于我们/福利待遇”等标题，后面的句子视为公司介绍段；遇到“岗位职责/任职要求/加分项”等标题，视为岗位要求段。
3. **判断是否是公司介绍句**：
   - 在公司介绍段内的句子 → 介绍句；
   - 含“致力于、专注于、领先的、旗下、成立于、独角兽”等强介绍词 → 介绍句（岗位要求段内且同时含“熟悉、负责”等要求词时除外）；
   - 含“公司、我们、产品、平台、客户”等弱介绍词，但没有任何要求词 → 介绍句。
4. **计数**：
   - 严格词出现在非介绍句中 → `ai_skill = 1`；
   - 宽泛词出现在非介绍句中，且该句有“熟悉、掌握、负责、使用、优先、专业”等要求线索（或位于岗位要求段）→ `ai_skill_broad = 1`；
   - 标题本身就是岗位名称，标题中的严格词和宽泛词直接计入，不做介绍句判断。
5. **专门的误判排除**：
   - “AI”和PS、CDR、Illustrator、平面设计、排版等同句出现 → 视为Adobe Illustrator，不计；
   - “CV”和简历、投递、邮箱同句 → 视为简历，不计；
   - “GPT”和分区、MBR、磁盘同句 → 视为分区表，不计；
   - Kimi、Claude等和联系人、微信、HR同句 → 视为人名，不计；
   - 英文缩写要求前后不是字母或数字：`ML`不匹配`HTML`、`500ml`；`AI`不匹配`MAIL`；
   - “LoRA”区分大小写，不匹配物联网的“LoRa”。
6. **缺失文本**：职位描述缺失且标题没有命中时，`ai_skill`为空值，不编码为0。

## 四、输出字段

`<features_root>/ai_skill_v0.1/ai_skill_{year}.parquet`，每条广告一行：

|字段|含义|
|---|---|
|`source_record_id`|来源记录ID，用于和`confirmed_core_v2`左连接|
|`ai_skill`|严格版0/1；文本缺失为空|
|`ai_skill_broad`|宽泛版0/1|
|`ai_genai`、`ai_traditional`|严格命中中是否含生成式/传统AI词|
|`ai_strict_terms`、`ai_broad_terms`|命中的词条编号，用`|`分隔|
|`ai_intro_only`|AI词只出现在公司介绍中|
|`ai_review_flag`|命中复核词|
|`ai_evidence`|第一条计入的句子（前120字），供人工核对|
|`ai_rule_version`|规则版本|

年度汇总`outputs/qc/ai_skill_v0.1_summary.csv`不含广告原文，可以上传GitHub。

## 五、人工标注规则

### 5.1 抽样

运行`12_build_ai_skill.py`后自动生成`<analysis_root>/ai_annotation_v0.1/annotation_sample.csv`（含广告原文，**不上传GitHub**），按程序结果分层抽取300条：

|层|条件|条数|主要用途|
|---|---|---:|---|
|strict_hit|`ai_skill=1`|100|估计查准率（判成AI的是否真是AI）|
|broad_only|只有宽泛版为1|60|决定宽泛词能否升级为严格词|
|intro_only|AI词只出现在公司介绍|40|检查介绍句判断是否误伤|
|review_only|只命中复核词|30|决定争议岗位怎么处理|
|no_hit|没有任何命中|70|估计漏判|

因为AI广告在总体中比例很低，未命中层70条很可能一条漏判也找不到。若时间允许，应再从未命中层中抽取“技术类岗位”（如标题含工程师、开发、数据）补充样本，专门找漏判。

### 5.2 标注时只看原文，不看程序结果

标注人应先遮住`ai_skill`等程序列，只读`job_title`和`job_description`，独立填写：

- `label_ai_skill`：1 = 岗位明确要求AI技能；0 = 不要求；9 = 无法判断；
- `label_ai_type`：traditional / generative / both / 空；
- `label_error_type`（与程序结果对比后填写）：见5.4；
- `annotator`：A或B；`note`：判断理由或疑问。

### 5.3 判为1的标准

满足任一条即标1：

1. 要求应聘者**掌握、熟悉、了解**某项AI技术、算法、框架或工具；
2. 岗位**职责**包括开发、训练、部署、调优AI模型或AI应用；
3. 要求应聘者**使用**AI工具（如ChatGPT、Midjourney）完成工作；
4. 把AI相关经验列为**优先或加分**条件。

判为0：

- AI只出现在公司介绍、产品介绍、行业描述中；
- “AI”实际指Illustrator等其他含义；
- 只要求“计算机/人工智能相关专业”，没有任何技能要求（**待项目组决定**，先标0并在note写“仅专业”）；
- 数据标注、AI训练师等岗位只做简单标注、没有AI技术要求（**待项目组决定**，先标0并在note写“标注类”）。

### 5.4 误判类型

|代码|含义|
|---|---|
|FP_intro|公司或产品介绍被判成技能|
|FP_homonym|同形异义词（Illustrator、CV、人名等）|
|FP_generic|泛泛提到AI，不构成技能要求|
|FN_missing_term|词典缺词导致漏判|
|FN_wrong_intro|岗位要求被误判为公司介绍|
|other|其他，在note说明|

### 5.5 双人复核与指标

1. 先由A、B各自独立标同一批50条，计算一致率（及Cohen's kappa），讨论分歧后修订本规则；
2. 再分工标完其余样本，分歧条目共同决定；
3. 报告：各层样本量、查准率 = 程序判1中人工也判1的比例、查全率 = 人工判1中程序也判1的比例（按分层权重换算到总体）、主要误判和漏判类型；
4. 根据误判修改词典，规则版本号加一，重新运行并在新样本上复核，不在同一批样本上反复调参。

## 六、待项目组决定的问题

1. “计算机、人工智能等相关专业”算不算AI技能要求？当前只进`ai_skill_broad`。
2. 标题含严格词（如“机器学习工程师”）而描述没有AI内容时，是否计为1？当前计为1。
3. 数据标注、AI训练师等是否算AI技能？当前不算，只做标记。
4. “算法工程师”描述中没有AI词时是否算？当前不算。
5. 使用ChatGPT等AI工具辅助办公是否算AI技能？当前算，归为生成式AI。

## 七、已知局限

- 规则只用手写样例测试过（`code/python/tests/test_ai_skill_matcher.py`，39条），尚未在真实广告上检验；
- 没有处理否定句（如“无需AI经验”），这类写法预计很少，在标注中观察；
- 一句话中同时有公司介绍和岗位要求时，按要求词优先处理，可能多判；
- 2018—2021年几乎不会出现生成式AI词，`ai_genai`的时间变化主要反映2022年以后。

## 八、运行方法

```bash
# 单元测试（不需要数据）
.venv/bin/python -m unittest discover -s code/python/tests

# 试跑2022年前5万条
.venv/bin/python code/python/12_build_ai_skill.py --years 2022 --limit 50000

# 全量运行（约15—30分钟）并抽取标注样本
.venv/bin/python code/python/12_build_ai_skill.py
```

Windows上把`.venv/bin/python`换成`.venv\Scripts\python.exe`。
