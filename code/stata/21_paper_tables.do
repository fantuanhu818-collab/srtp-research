* =============================================================================
* 21_paper_tables.do  论文格式描述性统计表（v1.0）
* 负责人：B（李宇白）  复核人：A（胡嘉琪）
*
* 用法：
*   do code/stata/21_paper_tables.do "<descriptive_input_all.dta>" "<输出目录>"
* Mac：scripts/run_stata_task.sh code/stata/21_paper_tables.do <输出目录>/paper_tables.log <dta> <输出目录>
*
* 输入：30_build_descriptive_input.py 生成的 descriptive_input_all.dta（核心变量+AI变量）
* 输出：<输出目录>/tables/paper_t1_summary.csv、paper_t2_balance.csv、paper_t3_by_year.csv
*       <输出目录>/paper_tables.xlsx、paper_tables.docx、paper_tables.log（末尾 STATA_TASK=PASS）
*
* 口径（经济学论文常用做法）：
*   1. 工资按年份在第1和第99百分位缩尾（winsorize），对数工资由缩尾后工资计算；原始工资同时报告；
*   2. 表1：全样本主要变量的观测数、均值、标准差、最小值、中位数、最大值；
*   3. 表2：AI岗位与非AI岗位的均值比较，报告差值、t检验（不等方差）和标准化差异
*      （Imbens & Rubin 2015：|标准化差异|>0.25 视为两组差异较大）；
*   4. 表3：分年份样本量、AI岗位占比、生成式AI占比、AI与非AI的对数工资差。
* 所有结果为描述性比较，不控制其他因素，不能解释为AI技能的工资效应。
* =============================================================================

version 16
clear all
set more off

args data_path out_dir
if "`data_path'" == "" | "`out_dir'" == "" {
    display as error "用法：do 21_paper_tables.do <dta> <输出目录>"
    exit 198
}
local tab "`out_dir'/tables"
capture mkdir "`out_dir'"
capture mkdir "`tab'"
local xlsx "`out_dir'/paper_tables.xlsx"
local docx "`out_dir'/paper_tables.docx"
capture log close paper
log using "`out_dir'/paper_tables.log", text replace name(paper)

* -----------------------------------------------------------------------------
* 1. 读入、变量准备
* -----------------------------------------------------------------------------
use "`data_path'", clear
foreach v in source_record_id year wage_mid education experience city_id ai_skill ai_skill_broad ai_genai ai_traditional {
    confirm variable `v'
}
isid source_record_id
quietly count
display "INPUT_ROWS=" r(N)
drop if missing(ai_skill)
quietly count
local n_ai_ok = r(N)
display "AI_NONMISSING_ROWS=`n_ai_ok'"

* 工资按年份缩尾（1%、99%）
generate double wage_w = wage_mid
quietly levelsof year, local(years)
foreach y of local years {
    quietly _pctile wage_mid if year == `y', percentiles(1 99)
    quietly replace wage_w = r(r1) if year == `y' & wage_mid < r(r1) & !missing(wage_mid)
    quietly replace wage_w = r(r2) if year == `y' & wage_mid > r(r2) & !missing(wage_mid)
}
generate double ln_wage_w = ln(wage_w)
generate double wage_w_k = wage_w / 1000
generate double wage_raw_k = wage_mid / 1000

* 学历、经验、城市虚拟变量（缺失保持缺失）
generate byte edu_college = inlist(education, "大专") if !missing(education)
generate byte edu_bachelor = inlist(education, "本科") if !missing(education)
generate byte edu_master_plus = inlist(education, "硕士", "博士") if !missing(education)
generate byte edu_unlimited = inlist(education, "不限") if !missing(education)
generate byte exp_none = inlist(experience, "不限/应届") if !missing(experience)
generate byte exp_3plus = inlist(experience, "3—5年", "5年以上") if !missing(experience)
generate byte city_tier1 = inlist(city_id, "北京", "上海", "广州", "深圳") if !missing(city_id) & city_id != ""

label variable wage_raw_k "月薪（千元，原始）"
label variable wage_w_k "月薪（千元，缩尾）"
label variable ln_wage_w "对数月薪（缩尾）"
label variable ai_skill "AI技能要求（严格版）"
label variable ai_skill_broad "AI技能要求（宽泛版）"
label variable ai_genai "生成式AI技能"
label variable ai_traditional "传统AI技能"
label variable edu_unlimited "学历不限"
label variable edu_college "大专"
label variable edu_bachelor "本科"
label variable edu_master_plus "硕士及以上"
label variable exp_none "经验不限/应届"
label variable exp_3plus "经验3年以上"
label variable city_tier1 "一线城市（北上广深）"

local vars wage_raw_k wage_w_k ln_wage_w ai_skill ai_skill_broad ai_genai ai_traditional ///
    edu_unlimited edu_college edu_bachelor edu_master_plus exp_none exp_3plus city_tier1

* -----------------------------------------------------------------------------
* 表1 主要变量描述统计
* -----------------------------------------------------------------------------
tempname h1
tempfile f1
postfile `h1' str40 变量 double(观测数 均值 标准差 最小值 中位数 最大值) using `f1'
foreach v of local vars {
    quietly summarize `v', detail
    local lab : variable label `v'
    post `h1' ("`lab'") (r(N)) (r(mean)) (r(sd)) (r(min)) (r(p50)) (r(max))
}
postclose `h1'

* -----------------------------------------------------------------------------
* 表2 AI岗位与非AI岗位均值比较
* -----------------------------------------------------------------------------
local bvars wage_raw_k wage_w_k ln_wage_w edu_unlimited edu_college edu_bachelor edu_master_plus ///
    exp_none exp_3plus city_tier1
tempname h2
tempfile f2
postfile `h2' str40 变量 double(非AI岗位均值 AI岗位均值 差值 标准误 t值 p值 标准化差异 非AI观测数 AI观测数) using `f2'
foreach v of local bvars {
    quietly ttest `v', by(ai_skill) unequal
    local m0 = r(mu_1)
    local m1 = r(mu_2)
    local nd = (`m1' - `m0') / sqrt((r(sd_1)^2 + r(sd_2)^2) / 2)
    local lab : variable label `v'
    post `h2' ("`lab'") (`m0') (`m1') (`m1' - `m0') (r(se)) (-r(t)) (r(p)) (`nd') (r(N_1)) (r(N_2))
}
postclose `h2'

* -----------------------------------------------------------------------------
* 表3 分年份
* -----------------------------------------------------------------------------
preserve
generate double lw_ai = ln_wage_w if ai_skill == 1
generate double lw_non = ln_wage_w if ai_skill == 0
collapse (count) 观测数=ai_skill (mean) AI岗位占比=ai_skill 宽泛版占比=ai_skill_broad ///
    生成式AI占比=ai_genai AI岗位对数工资=lw_ai 非AI岗位对数工资=lw_non, by(year)
generate double 对数工资差 = AI岗位对数工资 - 非AI岗位对数工资
foreach v in AI岗位占比 宽泛版占比 生成式AI占比 {
    replace `v' = `v' * 100
}
rename year 年份
tempfile f3
save `f3'
restore

* -----------------------------------------------------------------------------
* 导出：CSV、Excel、Word
* -----------------------------------------------------------------------------
putdocx begin, font("PingFang SC", 10)
putdocx paragraph, style(Title)
putdocx text ("描述性统计")
putdocx paragraph
putdocx text ("样本：2018—2025年招聘广告，AI变量可判断的样本`n_ai_ok'条。工资按年份在1%和99%分位缩尾。所有结果为描述性比较，不能解释为因果效应。")

local titles `" "表1 主要变量描述统计" "表2 AI岗位与非AI岗位的均值比较" "表3 分年份AI岗位占比与工资差" "'
local names paper_t1_summary paper_t2_balance paper_t3_by_year
local notes `" "注：月薪单位为千元；虚拟变量的均值即比例。" "注：差值=AI岗位均值−非AI岗位均值；t检验为不等方差；标准化差异=(均值差)/sqrt((方差1+方差2)/2)，绝对值大于0.25视为两组差异较大。" "注：占比单位为%；对数工资为缩尾后月薪的对数。" "'
forvalues i = 1/3 {
    use `f`i'', clear
    local name : word `i' of `names'
    local title : word `i' of `titles'
    local note : word `i' of `notes'
    export delimited using "`tab'/`name'.csv", replace
    export excel using "`xlsx'", sheet("`name'") sheetreplace firstrow(variables)
    quietly ds, has(type numeric)
    foreach v in `r(varlist)' {
        if inlist("`v'", "观测数", "非AI观测数", "AI观测数", "年份") format `v' %12.0fc
        else format `v' %9.3f
    }
    putdocx paragraph, style(Heading2)
    putdocx text ("`title'")
    putdocx table t`i' = data(_all), varnames layout(autofitcontents)
    putdocx paragraph
    putdocx text ("`note'"), font(, 8)
}
putdocx save "`docx'", replace

display "STATA_TASK=PASS"
log close paper
