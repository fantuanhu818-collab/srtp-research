# AI技能工资溢价研究与Stata学习手册

更新日期：2026-10-23

适用对象：第一次独立完成应用微观经济学研究、只掌握基础Stata操作的研究者。

> 学习目标：学完后，你应当能用自己的话说明研究问题和证据边界，读懂基准回归及扩展分析的Stata代码，检查样本、变量、固定效应和标准误，并根据日志与结果表判断分析是否可信。

> 当前状态：项目仍处于数据审计阶段。本手册中的变量名和代码是计划采用的规范模板，不代表正式数据已经生成，也不代表模型已经得到最终结果。正式回归前，仍需完成2018—2025年数据审计、AI词典验证和变量口径确认。

<table-of-contents />

# 第一章　这个研究究竟在做什么

## 1.1 一句话研究问题

在企业、职业、城市、时间以及岗位要求尽量可比的条件下，招聘广告明确要求AI技能时，企业发布的工资是否更高？这种工资差异是否随职业、AI暴露度和ChatGPT发布前后而变化？

研究使用2018—2025年智联招聘广告。**一条观测是一个招聘广告，而不是一个劳动者。**因此，研究测量的是企业发布的岗位要求和发布工资，不能直接当作劳动者最终获得的工资。

## 1.2 三个层次的问题

1. **基准问题**：要求AI技能的招聘广告，工资是否比其他相似广告高？
2. **异质性问题**：这种工资差异是否因职业、行业、城市层级或职业AI暴露度而不同？
3. **时间变化问题**：2022年11月ChatGPT发布以后，AI技能对应的工资差异是否发生变化？

## 1.3 最重要的证据边界

如果回归发现AI岗位工资更高，可以说：

> 在控制模型中列出的岗位和市场特征后，要求AI技能的招聘广告与更高的发布工资相关。

不能直接说：

> 学会AI技能会使任何人的工资提高同样比例。

原因是企业可能把AI技能写在本来就更复杂、更高级或更难招聘的岗位中。固定效应和控制变量只能减少一部分不可比性，不能保证消除所有遗漏因素。

## 1.4 从原始数据到论文结果

```text
原始招聘CSV
→ Python：数据审计、工资清洗、文本识别、变量构造
→ Parquet：保留完整清洗数据
→ DTA：只保留Stata分析所需变量
→ Stata：描述统计、回归、表格和图
→ 人工审核代码、日志和结果
→ 写入论文
```

Python负责处理大规模文本和清洗；Stata负责统计模型。Stata代码不能替代前面的数据质量检查。

# 第二章　理解数据和变量

## 2.1 计划使用的核心变量

- `wage_mid`：工资区间的中点，例如最低月薪8000、最高月薪12000，中点为10000。
- `ln_wage`：`wage_mid`的自然对数，是基准回归的因变量。
- `ai_skill`：招聘广告是否明确要求AI技能，要求为1，否则为0。
- `education`：学历要求。
- `experience`：工作经验要求转换后的数值或分类变量。
- `other_skill_*`：软件、认知、社交、管理等非AI技能要求。
- `skill_count`：岗位描述中识别出的技能数量。
- `description_length`：职位描述长度。
- `firm_id`：清洗后的企业标识。
- `occupation_id`：统一后的职业分类。
- `city_id`：统一后的工作城市。
- `industry_id`：企业行业。
- `year_month`：招聘发布年月。
- `ai_exposure`：职业层面的AI暴露度。
- `post_chatgpt`：2022年11月以后为1，此前为0。

这些英文变量名是为了让程序稳定、便于复现。正式分析前必须建立“英文变量名—中文含义—生成方法—缺失值规则”的对应说明。

## 2.2 为什么通常使用工资对数

招聘工资往往右偏：大部分岗位集中在中低区间，少数岗位工资非常高。取自然对数可以减弱极端值影响，并使系数更容易解释为近似百分比差异。

```text
gen ln_wage = ln(wage_mid)
```

这行代码只有在`wage_mid>0`时才有意义。审核时先运行：

```text
count if wage_mid <= 0 & !missing(wage_mid)
count if missing(wage_mid)
summarize wage_mid, detail
```

不能为了让程序运行而直接删除异常工资。应先保留异常标记，说明异常来自原始数据还是清洗规则，再决定正式样本。

## 2.3 AI变量测量的是什么

`ai_skill=1`表示文本规则判断招聘广告明确要求AI相关技能。它不等于：

- 企业已经采用AI；
- 劳动者实际掌握AI；
- 该职业容易被AI替代；
- AI技能是工资差异的唯一原因。

因此，AI词典必须经过人工标注。至少要报告人工样本数量、准确率、查准率、查全率，以及主要误判和漏判类型。

## 2.4 缺失值会改变回归样本

Stata回归会自动删除参与模型的任一变量存在缺失值的记录。模型加入的变量越多，样本可能越少。如果不同模型的样本不同，系数变化既可能来自控制变量，也可能来自样本变化。

因此，正式比较模型时通常先定义共同样本：

```text
gen byte sample_base = !missing(ln_wage, ai_skill, education, experience, ///
    other_skill_software, other_skill_social, other_skill_cognitive, ///
    firm_id, occupation_id, city_id, year_month)

tabulate sample_base
```

`byte`表示用较小存储空间保存0/1变量；`!missing()`表示括号内变量都不缺失。

# 第三章　基准模型背后的经济学

## 3.1 基准模型

计划中的基准模型可以写成：

$$
\ln(Wage_i)=\alpha+\beta AI_i+\gamma'X_i+\mu_f+\lambda_{oc}+\tau_t+\varepsilon_i
$$

各部分含义：

- $\ln(Wage_i)$：第`i`条招聘广告的工资对数。
- $AI_i$：该广告是否要求AI技能。
- $X_i$：学历、经验、其他技能等可以观察到的岗位要求。
- $\mu_f$：企业固定效应。
- $\lambda_{oc}$：职业与城市形成的劳动力市场固定效应。
- $\tau_t$：招聘时间固定效应。
- $\varepsilon_i$：模型没有观察到的其他因素。
- $\beta$：本研究最关心的AI技能工资差异。

## 3.2 “控制变量”在做什么

假设AI岗位更常要求本科以上学历。如果不控制学历，AI系数可能同时包含学历回报。加入学历、经验和其他技能，是为了让AI岗位与非AI岗位更可比。

但控制变量不是越多越好。应满足两点：

1. 它能解释工资和AI技能要求之间的系统差异；
2. 它不是AI技能影响工资过程中产生的中间结果。

每加入一个变量，都应能回答“为什么要控制它”。

## 3.3 固定效应在做什么

固定效应可以理解为“先扣除某个分组本身的平均差异，再进行比较”。

- **企业固定效应**：尽量在同一家企业内部比较AI岗位和非AI岗位，减少企业薪酬水平差异的影响。
- **职业×城市固定效应**：在同一职业、同一城市形成的劳动力市场中比较，减少职业结构和地区工资水平差异。
- **时间固定效应**：扣除某个月所有岗位共同面对的宏观变化、季节变化和通胀等因素。

加入企业固定效应后，`ai_skill`的系数主要依靠“同一家企业内部不同广告之间的AI要求差异”识别。如果某家企业所有广告的`ai_skill`始终相同，它对这一系数没有组内识别贡献。

## 3.4 为什么要渐进式加入控制

基准表不应只给一个最复杂模型。建议依次报告：

1. M1：只加入`ai_skill`；
2. M2：加入学历、经验和其他技能；
3. M3：加入职业×城市和时间固定效应；
4. M4：进一步加入企业固定效应。

这样可以观察AI系数在哪一步明显变化，并解释变化来自怎样的可比范围。

## 3.5 标准误和聚类

同一家企业发布的广告可能受到共同的薪酬制度、招聘策略和数据录入方式影响，误差项可能相关。因此，基准模型计划在企业层面使用聚类稳健标准误：

```text
vce(cluster firm_id)
```

聚类标准误主要影响标准误、置信区间和显著性，不改变同一OLS模型的系数。最终聚类层级必须结合数据结构和研究设计决定，不能因为某种设定更显著就选择它。

## 3.6 怎样解释工资对数模型的系数

如果`ai_skill`是0/1变量、估计系数为`0.08`，近似解释是AI岗位工资高8%。更准确的换算是：

```text
display 100 * (exp(_b[ai_skill]) - 1)
```

结果约为8.33%。正确表述是“与高约8.33%的发布工资相关”，不能自动写成“导致工资提高8.33%”。

# 第四章　先学会阅读Stata语言

## 4.1 一条命令的基本结构

```text
regress ln_wage ai_skill i.education, vce(cluster firm_id)
```

读取顺序：

1. `regress`：使用线性回归；
2. 第一个变量`ln_wage`：因变量；
3. 后面的变量：解释变量和控制变量；
4. 逗号后：回归选项；
5. `vce(cluster firm_id)`：企业层面聚类标准误。

## 4.2 最常见的符号

- `*`：一行注释的开头。
- `//`：同一行后面的注释。
- `///`：命令换行，下一行仍属于同一条命令。
- `if`：只对满足条件的观测执行。
- `==`：判断是否相等。
- `!=`：判断是否不相等。
- `&`：并且。
- `|`：或者。
- `!missing(x)`：`x`不是缺失值。
- `i.education`：把学历当作分类变量并自动生成虚拟变量。
- `c.experience`：把经验当作连续变量。
- `#`：只加入交互项。
- `##`：同时加入两边的主效应和交互项。

## 4.3 生成、修改和删除

```text
gen wage_mid = (wage_min + wage_max) / 2
replace wage_mid = . if wage_mid <= 0
keep if sample_base == 1
drop if duplicate_flag == 1
```

- `gen`创建新变量；
- `replace`修改已有变量；
- `keep`只保留满足条件的记录；
- `drop`删除满足条件的记录。

正式项目中，`replace`、`keep`和`drop`都必须有注释和前后记录数。基准分析更推荐用`if sample_base==1`指定样本，而不是不断永久删除数据。

## 4.4 Stata中的缺失值陷阱

数值缺失值写作`.`。在Stata的排序规则中，它比普通数字大。因此：

```text
count if wage_mid > 100000
```

可能把缺失值也算进去。更安全的是：

```text
count if wage_mid > 100000 & !missing(wage_mid)
```

# 第五章　从打开数据到完成基准回归

## 5.1 do文件开头

```text
version 18
clear all
set more off
capture log close

log using "outputs/analysis/baseline_regression.log", text replace
```

- `version 18`：按照Stata 18的规则解释代码。
- `clear all`：清空内存中的旧数据和对象。
- `set more off`：运行时不因屏幕分页暂停。
- `capture log close`：如果旧日志仍打开，尝试关闭；即使没有日志也不报错中断。
- `log using`：把命令和输出保存为日志。

日志是审核证据。只有结果表、没有日志，无法确认程序是否完整运行。

## 5.2 读取数据并确认身份

```text
use "D:/SRTP/工作数据/stata/baseline_sample.dta", clear

describe
count
datasignature
```

- `describe`检查变量和类型；
- `count`记录总行数；
- `datasignature`生成与当前数据内容有关的签名，帮助确认数据是否变化。

正式代码将从本机配置读取路径，不应把A电脑的绝对路径复制到B电脑。

## 5.3 数据质量检查

```text
codebook ln_wage ai_skill education experience
summarize wage_mid ln_wage experience, detail
tabulate ai_skill, missing
misstable summarize ln_wage ai_skill education experience ///
    firm_id occupation_id city_id year_month

count if wage_mid <= 0 & !missing(wage_mid)
count if !inlist(ai_skill, 0, 1) & !missing(ai_skill)
```

审核目标不是“命令没有报错”，而是检查：

- 工资是否存在不可能值；
- `ai_skill`是否只有0和1；
- 分类变量是否出现异常编码；
- 主要变量缺失多少；
- 记录数是否与Python导出报告一致。

## 5.4 固定共同样本

```text
gen byte sample_base = !missing(ln_wage, ai_skill, education, experience, ///
    other_skill_software, other_skill_social, other_skill_cognitive, ///
    firm_id, occupation_id, city_id, year_month)

count if sample_base == 1
tabulate ai_skill if sample_base == 1
summarize ln_wage if sample_base == 1, detail
```

如果还要加入其他技能控制变量，共同样本也必须包含这些变量。样本规则应先写清楚，再运行模型。

## 5.5 安装并检查高维固定效应命令

Stata 18中计划使用第三方命令`reghdfe`处理多组高维固定效应。第一次安装：

```text
ssc install ftools, replace
ssc install reghdfe, replace
```

正式程序只检查版本，不应每次自动更新：

```text
which reghdfe
```

日志必须记录使用的是哪一版命令，避免A和B使用不同版本。

## 5.6 渐进式基准回归

以下代码是学习模板，最终控制变量和固定效应需由研究设计确认。

```text
* M1：原始工资差异
regress ln_wage ai_skill if sample_base == 1, vce(cluster firm_id)
estimates store M1

* M2：加入岗位要求
regress ln_wage ai_skill i.education ///
    c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, vce(cluster firm_id)
estimates store M2

* M3：加入职业×城市和招聘年月固定效应
reghdfe ln_wage ai_skill i.education ///
    c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(occupation_id#city_id year_month) ///
    vce(cluster firm_id)
estimates store M3

* M4：进一步加入企业固定效应
reghdfe ln_wage ai_skill i.education ///
    c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id occupation_id#city_id year_month) ///
    vce(cluster firm_id)
estimates store M4
```

逐行审核时要问：

- 四个模型是否使用同一共同样本？
- `ai_skill`的定义是否完全相同？
- M2增加了哪些岗位要求？
- M3和M4分别把比较范围缩小到哪里？
- Stata是否报告变量被省略、单例组被删除或未收敛？
- 企业标识是否可靠？如果企业标识尚未统一，M4不能成为正式结果。

## 5.7 检查实际回归样本

每次回归后，`e(sample)`标记真正进入该模型的记录：

```text
count if e(sample)
tabulate ai_skill if e(sample)
summarize ln_wage if e(sample)
```

如果实际样本数与`sample_base`不一致，要查明是否还有缺失值、共线性、单例组或其他自动删除。

## 5.8 输出和保存结果

```text
estimates table M1 M2 M3 M4, ///
    keep(ai_skill) b(%9.4f) se(%9.4f) stats(N r2)

etable, estimates(M1 M2 M3 M4) ///
    keep(ai_skill) showstars ///
    export("outputs/analysis/baseline_models.xlsx", replace)

display "STATA_TASK=PASS"
log close
```

`estimates store`保存模型；`estimates table`在Stata中比较结果；`etable`生成可导出的表。星号只能表示统计显著性，不能代表经济意义或因果性。

# 第六章　怎样读一张回归表

## 6.1 先看样本量

检查每列的`N`是否一致。如果加入控制变量后样本突然减少，先分析缺失值，不要马上解释系数变化。

## 6.2 再看AI系数

比较四个模型中`ai_skill`的：

- 正负方向；
- 大小；
- 标准误；
- 置信区间；
- 加入控制和固定效应后的变化。

如果M1为0.20、M4降为0.05，可以解释为原始工资差异中的很大部分与企业、职业、城市、时间和岗位要求差异有关。M4剩余部分仍然不一定是因果效应。

## 6.3 显著不等于重要

样本有数百万条时，很小的差异也可能统计显著。应同时报告：

- 系数对应的百分比；
- 置信区间；
- 与平均工资相比是否具有实际意义；
- 不同模型下是否稳定。

## 6.4 `omitted`不等于系数为零

Stata显示`omitted`通常意味着该变量是参照组，或与其他变量完全共线，无法单独估计。审核时应查明是哪一种情况。

# 第七章　AI暴露度与异质性分析

## 7.1 AI暴露度交互模型

模型写作：

$$
\ln(Wage_i)=\alpha+\beta_1 AI_i+\beta_2 Exposure_o+\beta_3(AI_i\times Exposure_o)+\cdots
$$

其中`β3`回答：职业AI暴露度越高时，AI技能对应的工资差异是否更大。

```text
reghdfe ln_wage i.ai_skill##c.ai_exposure ///
    i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id occupation_id#city_id year_month) ///
    vce(cluster firm_id)

margins, dydx(ai_skill) at(ai_exposure=(-2 -1 0 1 2))
marginsplot
```

- `i.ai_skill##c.ai_exposure`同时加入AI变量、暴露度和交互项；
- `margins`计算不同暴露度下AI岗位与非AI岗位的预测工资差异；
- 如果职业固定效应已经吸收了不随时间变化的`ai_exposure`主效应，Stata可能把主效应省略，但交互项仍可能识别。

AI暴露度表示职业任务与AI能力的关联程度，不等于替代概率。正交互项可能表示互补价值，也可能反映高暴露职业中尚未控制的岗位复杂度。

## 7.2 职业、行业和城市异质性

比较不同组的系数时，优先在同一回归中使用交互项：

```text
reghdfe ln_wage i.ai_skill##i.occupation_group ///
    i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id city_id year_month) ///
    vce(cluster firm_id)

margins occupation_group, dydx(ai_skill)
```

分别跑子样本回归可以作为补充，但“一个组显著、另一个组不显著”不等于两组系数显著不同。交互项可以直接检验差异。

# 第八章　ChatGPT前后变化与DID

## 8.1 先做描述性的溢价时间曲线

可以估计每个季度的AI技能工资差异：

```text
local base_q = yq(2022, 3)

reghdfe ln_wage i.ai_skill##ib`base_q'.quarter_id ///
    i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id occupation_id#city_id quarter_id) ///
    vce(cluster firm_id)

margins quarter_id, dydx(ai_skill)
marginsplot, yline(0)
```

`local base_q = yq(2022, 3)`把2022年第三季度设置为最后一个完整的ChatGPT发布前季度；`ib`把它设为参照期。正式代码仍需根据最终季度变量的编码检查。

这张图回答“各季度AI岗位与非AI岗位的工资差异如何变化”，首先属于描述性动态分析。

## 8.2 ChatGPT前后交互模型

```text
reghdfe ln_wage i.ai_skill##i.post_chatgpt ///
    i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id occupation_id#city_id year_month) ///
    vce(cluster firm_id)
```

交互项`1.ai_skill#1.post_chatgpt`表示ChatGPT发布后，AI岗位相对非AI岗位的工资差异比发布前变化了多少。

## 8.3 为什么这不自动构成可信因果DID

标准DID需要明确：

1. 谁是处理组，谁是对照组；
2. 处理组成员不能由冲击后的结果随意决定；
3. 如果没有ChatGPT冲击，两组结果应具有可辩护的平行趋势；
4. 同期没有只影响处理组的其他重大变化；
5. 招聘样本构成变化不会机械地产生结果。

招聘广告是否要求AI技能本身会随ChatGPT发布而变化，因此直接把`ai_skill`当作固定处理组存在选择问题。正式论文在因果设计未论证前，应把这一部分称为“ChatGPT发布前后的AI技能溢价变化”或“DID式交互分析”，不要仅凭一条交互项宣称ChatGPT造成了工资变化。

如果以后使用预先确定的高AI暴露职业作为处理组，还需检验处理前趋势，并明确研究的是岗位工资、AI需求还是二者的关系。

# 第九章　稳健性检验在检查什么

稳健性检验不是机械地多跑几次，而是针对某个具体担忧。

## 9.1 工资口径

担忧：工资区间中点或极端值影响结果。

- 使用区间中点和其他合理代表值；
- 对异常值采用事先说明的缩尾规则；
- 限定工资上下限均有效的样本；
- 对比不同口径下核心系数。

## 9.2 AI词典口径

担忧：关键词误判和漏判。

- 使用严格词典与扩展词典；
- 排除容易误判的普通英文词；
- 区分传统AI、生成式AI、开发型技能和应用型技能；
- 在人工标注样本中报告识别质量。

## 9.3 岗位复杂度

担忧：AI岗位只是总体技能要求更多。

- 控制其他技能类别；
- 控制技能数量和职位描述长度；
- 比较同时要求软件技能的岗位；
- 在更细职业范围内比较。

## 9.4 固定效应和样本范围

担忧：结果由某些行业、城市、年份或企业推动。

- 更换固定效应组合；
- 排除极端年份或样本特别小的组；
- 分职业、行业、城市层级报告；
- 检查企业固定效应样本与全样本的差异。

每项稳健性检验都应写明“担忧—处理方法—结果是否改变”，不能只陈列更多回归表。

# 第十章　完整do文件应当长什么样

```text
****************************************************
* 项目：AI技能工资溢价
* 任务：基准回归
* 输入：baseline_sample.dta
* 输出：日志、模型表、样本检查表
* 原始数据：只读
****************************************************

version 18
clear all
set more off
capture log close
log using "outputs/analysis/baseline_regression.log", text replace

* 1. 读取数据
use "D:/SRTP/工作数据/stata/baseline_sample.dta", clear
count
describe
datasignature

* 2. 检查核心变量
summarize wage_mid ln_wage experience, detail
tabulate ai_skill, missing
misstable summarize ln_wage ai_skill education experience ///
    firm_id occupation_id city_id year_month
count if wage_mid <= 0 & !missing(wage_mid)
count if !inlist(ai_skill, 0, 1) & !missing(ai_skill)

* 3. 定义共同样本
gen byte sample_base = !missing(ln_wage, ai_skill, education, experience, ///
    other_skill_software, other_skill_social, other_skill_cognitive, ///
    firm_id, occupation_id, city_id, year_month)
count if sample_base == 1

* 4. 描述统计
summarize ln_wage ai_skill experience if sample_base == 1
tabulate education if sample_base == 1, missing

* 5. 渐进式模型
regress ln_wage ai_skill if sample_base == 1, vce(cluster firm_id)
estimates store M1

regress ln_wage ai_skill i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, vce(cluster firm_id)
estimates store M2

reghdfe ln_wage ai_skill i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(occupation_id#city_id year_month) vce(cluster firm_id)
estimates store M3

reghdfe ln_wage ai_skill i.education c.experience##c.experience ///
    other_skill_software other_skill_social other_skill_cognitive ///
    if sample_base == 1, ///
    absorb(firm_id occupation_id#city_id year_month) vce(cluster firm_id)
estimates store M4

* 6. 检查最后一个模型的实际样本
count if e(sample)
tabulate ai_skill if e(sample)

* 7. 解释AI系数
display "AI coefficient = " _b[ai_skill]
display "Exact percent difference = " 100*(exp(_b[ai_skill])-1)

* 8. 输出结果
estimates table M1 M2 M3 M4, ///
    keep(ai_skill) b(%9.4f) se(%9.4f) stats(N r2)

etable, estimates(M1 M2 M3 M4) keep(ai_skill) showstars ///
    export("outputs/analysis/baseline_models.xlsx", replace)

display "STATA_TASK=PASS"
log close
```

这份代码只有在最终变量名、样本规则和路径确定后才能运行。真正的审核不是确认代码“看起来很专业”，而是把每一段与研究问题对应起来。

# 第十一章　审核Codex代码的固定清单

每次正式运行Stata前，逐项回答：

- [ ] 输入数据是哪一版？生成日期、记录数和代码版本是什么？
- [ ] 一行数据代表招聘广告、岗位还是企业？
- [ ] 因变量怎样构造？工资异常怎样处理？
- [ ] `ai_skill`怎样识别？人工验证结果如何？
- [ ] 哪些记录不进入回归？每个条件删除多少条？
- [ ] 不同模型是否使用共同样本？
- [ ] 控制变量分别解决什么可比性问题？
- [ ] 固定效应使我们在什么范围内比较？
- [ ] 标准误为什么在这个层级聚类？
- [ ] 是否出现`omitted`、单例组删除或未收敛？
- [ ] 系数换算成百分比是多少？置信区间多宽？
- [ ] 结果是相关关系还是因果关系？
- [ ] do文件、日志、结果表和数据版本能否一一对应？

只要其中一项回答不了，就先不要把回归数字写入论文。

# 第十二章　建议的学习顺序

## 第一阶段：能看懂数据

练习`use`、`describe`、`codebook`、`summarize`、`tabulate`、`count`、`misstable`。目标是能够独立判断变量类型、分布、异常和缺失。

## 第二阶段：能看懂样本处理

练习`gen`、`replace`、`if`、`keep`、`drop`和`missing()`。目标是看到一条样本筛选代码，就能说出哪些记录被保留或删除。

## 第三阶段：能看懂普通回归

练习`regress`、`i.`、`c.`、`#`、`##`和`vce()`。目标是能指出因变量、核心解释变量、控制变量、参照组和标准误类型。

## 第四阶段：能看懂固定效应

学习`reghdfe`、`absorb()`和聚类标准误。目标是能用一句话说清“这个模型是在谁与谁之间比较”。

## 第五阶段：能审查和解释结果

学习`e(sample)`、`estimates store`、`estimates table`、`etable`和系数百分比换算。目标是独立检查样本量变化、解释系数并指出证据边界。

## 第六阶段：学习扩展模型

在基准回归审核通过后，再学习交互项、`margins`、`marginsplot`、异质性分析和DID。不要在基准样本和变量尚未稳定时追求复杂模型。

# 第十三章　你是否已经真正掌握

不用看答案，尝试回答：

1. 为什么本研究的一行数据不是一个劳动者？
2. 为什么工资要取对数？取对数前要检查什么？
3. `regress ln_wage ai_skill i.education`每一部分是什么意思？
4. 为什么不同模型最好使用共同样本？
5. 企业固定效应加入后，AI系数来自什么比较？
6. `vce(cluster firm_id)`改变的主要是系数还是标准误？
7. `i.ai_skill##c.ai_exposure`中的交互项回答什么问题？
8. 为什么ChatGPT发布前后交互项不自动等于因果效应？
9. AI系数0.08应该如何准确换算和表述？
10. 如果M1到M4的AI系数逐步下降，你会怎样解释？

能够用自己的话回答这十题，并能逐行解释第五章代码，就已经具备独立审核基准回归的基础。

# 进一步查阅

- [Stata官方：线性回归regress](https://www.stata.com/manuals/rregress.pdf)
- [Stata官方：因子变量](https://www.stata.com/features/overview/factor-variables/)
- [Stata官方：稳健与聚类标准误](https://www.stata.com/support/faqs/statistics/standard-errors-and-vce-cluster-option/)
- [Stata官方：保存估计结果](https://www.stata.com/manuals/restimates.pdf)
- [Stata官方：输出回归表](https://www.stata.com/support/faqs/reporting/export-regression-results-table-formats/)
- [reghdfe快速入门](https://scorreia.com/software/reghdfe/quickstart.html)
- Alekseeva等（2021）：*The Demand for AI Skills in the Labor Market*
- Deming与Kahn（2018）：*Skill Requirements across Firms and Labor Markets*

