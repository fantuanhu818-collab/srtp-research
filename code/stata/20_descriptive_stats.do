* =============================================================================
* 20_descriptive_stats.do  描述性统计框架 v0.1
* 负责人：B（李宇白）  复核人：A（胡嘉琪）
*
* 用法（Stata命令窗口或批处理）：
*   do code/stata/20_descriptive_stats.do "<分析数据.dta>" "<输出目录>" [年份|all]
* 例：
*   do code/stata/20_descriptive_stats.do "D:/SRTP/工作数据/stata/analysis_2022.dta" "outputs/analysis/descriptive_2022" 2022
*
* 输入数据接口见 docs/描述性统计框架说明_v0.1.md：
*   必需：source_record_id year year_month wage_mid ln_wage education experience city_id ai_skill
*   可选：ai_skill_broad ai_genai ai_traditional firm_id industry_id occupation_id
* 可选变量存在时自动输出对应表，不存在时跳过。
*
* 输出：<输出目录> 下的 tables 文件夹（CSV汇总表，可进Git）、descriptive_tables.xlsx、
*       figures 文件夹（PNG图）、descriptive_stats.log。日志末尾出现 STATA_TASK=PASS 才算成功。
* 所有结果是描述性比较，不控制任何其他因素，不能解释为AI技能的工资效应。
* =============================================================================

version 16
clear all
set more off
capture log close _all

args data_path out_dir sample_year
if `"`data_path'"' == "" {
    display as error "缺少参数：do 20_descriptive_stats.do <分析数据.dta> <输出目录> [年份|all]"
    exit 198
}
if `"`out_dir'"' == "" local out_dir "outputs/analysis/descriptive"
if `"`sample_year'"' == "" local sample_year "all"

local tab "`out_dir'/tables"
local fig "`out_dir'/figures"
local xlsx "`out_dir'/descriptive_tables.xlsx"
capture mkdir "`out_dir'"
capture mkdir "`tab'"
capture mkdir "`fig'"
confirm file "`out_dir'/."
log using "`out_dir'/descriptive_stats.log", text replace name(desc)
capture erase "`xlsx'"

if c(os) == "MacOSX" graph set window fontface "PingFang SC"
if c(os) == "Windows" graph set window fontface "Microsoft YaHei"
set scheme s2color

display "DATA=`data_path'"
display "SAMPLE_YEAR=`sample_year'"

* -----------------------------------------------------------------------------
* 工具：把当前内存中的表同时导出为CSV和Excel工作表
* -----------------------------------------------------------------------------
capture program drop export_table
program define export_table
    args name tab xlsx
    export delimited using "`tab'/`name'.csv", replace
    export excel using "`xlsx'", sheet("`name'") sheetreplace firstrow(variables)
    display "TABLE_WRITTEN=`name' rows=" _N
end

* 工具：保存当前图。总是保存可编辑的.gph；优先PNG，
* Mac版Stata 16批处理不支持PNG时改存PDF。
capture program drop export_graph
program define export_graph
    args name fig
    graph save "`fig'/`name'.gph", replace
    capture graph export "`fig'/`name'.png", replace width(1600)
    if _rc {
        graph export "`fig'/`name'.pdf", replace
        display "GRAPH_WRITTEN=`name'.pdf（本机批处理不支持PNG）"
    }
    else display "GRAPH_WRITTEN=`name'.png"
end

* -----------------------------------------------------------------------------
* 1. 读入并检查数据
* -----------------------------------------------------------------------------
use "`data_path'", clear
foreach v in source_record_id year year_month wage_mid ln_wage education experience city_id ai_skill {
    capture confirm variable `v'
    if _rc {
        display as error "缺少必需变量：`v'"
        exit 111
    }
}
isid source_record_id
if "`sample_year'" != "all" keep if year == `sample_year'
quietly count
if r(N) == 0 {
    display as error "样本为空：year == `sample_year'"
    exit 2000
}
display "INPUT_ROWS=" r(N)

* 可选AI细分变量
local ai_vars "ai_skill"
foreach v in ai_skill_broad ai_genai ai_traditional {
    capture confirm variable `v'
    if !_rc local ai_vars "`ai_vars' `v'"
}
display "AI_VARS=`ai_vars'"
assert inlist(ai_skill, 0, 1, .)
assert wage_mid > 0 if !missing(wage_mid)

* -----------------------------------------------------------------------------
* 2. 变量准备：类别按固定顺序编码；生成招聘月份
* -----------------------------------------------------------------------------
label define edu_lbl 1 "不限" 2 "高中及以下" 3 "大专" 4 "本科" 5 "硕士" 6 "博士"
label define exp_lbl 1 "不限/应届" 2 "1年以内" 3 "1—3年" 4 "3—5年" 5 "5年以上"
label define ai_lbl 0 "非AI岗位" 1 "AI岗位"
* noextend：出现标签以外的取值时直接报错，防止口径不一致被悄悄吞掉
encode education, generate(edu_cat) label(edu_lbl) noextend
encode experience, generate(exp_cat) label(exp_lbl) noextend
label values ai_skill ai_lbl

capture confirm string variable year_month
if !_rc {
    generate ym = monthly(substr(year_month, 1, 7), "YM")
}
else {
    local fmt : format year_month
    if strpos("`fmt'", "%tc") generate ym = mofd(dofc(year_month))
    else if strpos("`fmt'", "%td") generate ym = mofd(year_month)
    else if strpos("`fmt'", "%tm") generate ym = year_month
    else {
        display as error "year_month 格式无法识别：`fmt'"
        exit 459
    }
}
format ym %tm
assert !missing(ym)

* 分组工资：用于比较AI与非AI岗位
generate double ln_wage_ai = ln_wage if ai_skill == 1
generate double ln_wage_nonai = ln_wage if ai_skill == 0
generate double wage_ai = wage_mid if ai_skill == 1
generate double wage_nonai = wage_mid if ai_skill == 0
generate byte s_desc = !missing(ln_wage, ai_skill)

* -----------------------------------------------------------------------------
* T1 样本构成：每一步剩多少条
* -----------------------------------------------------------------------------
tempname pf
tempfile t1
postfile `pf' str100 step double n using `t1', replace
quietly count
post `pf' ("分析数据全部记录") (r(N))
quietly count if !missing(ln_wage)
post `pf' ("工资有效") (r(N))
quietly count if missing(ai_skill)
post `pf' ("AI技能无法判断（文本缺失）") (r(N))
quietly count if s_desc
post `pf' ("描述统计样本（工资与AI均有效）") (r(N))
quietly count if s_desc & ai_skill == 1
post `pf' ("其中AI岗位") (r(N))
quietly count if missing(edu_cat)
post `pf' ("学历缺失（保留）") (r(N))
quietly count if missing(exp_cat)
post `pf' ("经验缺失（保留）") (r(N))
quietly count if missing(city_id) | city_id == ""
post `pf' ("城市缺失（保留）") (r(N))
postclose `pf'
preserve
use `t1', clear
export_table t1_sample_flow "`tab'" "`xlsx'"
list, noobs clean
restore

keep if s_desc

* -----------------------------------------------------------------------------
* T2 主要变量描述统计：全样本、非AI岗位、AI岗位
* -----------------------------------------------------------------------------
tempfile t2
postfile `pf' str30 group str40 variable double(n mean sd min p10 p50 p90 max) using `t2', replace
foreach g in all 0 1 {
    local cond = cond("`g'" == "all", "", "if ai_skill == `g'")
    local gname = cond("`g'" == "all", "全样本", cond("`g'" == "1", "AI岗位", "非AI岗位"))
    foreach v in wage_mid ln_wage `ai_vars' {
        quietly summarize `v' `cond', detail
        post `pf' ("`gname'") ("`v'") (r(N)) (r(mean)) (r(sd)) (r(min)) (r(p10)) (r(p50)) (r(p90)) (r(max))
    }
}
postclose `pf'
preserve
use `t2', clear
export_table t2_summary_stats "`tab'" "`xlsx'"
list group variable n mean p50, noobs clean
restore

* -----------------------------------------------------------------------------
* 分组汇总：AI岗位占比、工资、AI与非AI的原始对数工资差
* -----------------------------------------------------------------------------
capture program drop share_table
program define share_table
    syntax varname, name(string) tab(string) xlsx(string) aivars(string) [top(integer 0)]
    preserve
    drop if missing(`varlist')
    capture confirm string variable `varlist'
    if !_rc drop if `varlist' == ""
    collapse (count) n = ln_wage (sum) n_ai = ai_skill (mean) `aivars' ///
        (mean) wage_mean = wage_mid (p50) wage_p50 = wage_mid ///
        (mean) wage_mean_ai = wage_ai wage_mean_nonai = wage_nonai ///
        (mean) ln_wage_mean = ln_wage ln_wage_ai ln_wage_nonai, by(`varlist')
    generate double raw_ln_gap = ln_wage_ai - ln_wage_nonai
    label variable raw_ln_gap "AI与非AI岗位平均对数工资之差（未控制任何因素）"
    if `top' > 0 {
        gsort -n
        keep in 1/`=min(`top', _N)'
    }
    export_table `name' "`tab'" "`xlsx'"
    restore
end

local opts "tab(`tab') xlsx(`xlsx') aivars(`ai_vars')"
share_table year, name(t3_by_year) `opts'
share_table ym, name(t4_by_month) `opts'
share_table edu_cat, name(t5_by_education) `opts'
share_table exp_cat, name(t6_by_experience) `opts'
share_table city_id, name(t7_by_city_top30) top(30) `opts'
foreach v in industry_id occupation_id {
    capture confirm variable `v'
    if !_rc share_table `v', name(t8_by_`v'_top30) top(30) `opts'
    else display "SKIP_OPTIONAL=`v'（变量尚未构建）"
}

* -----------------------------------------------------------------------------
* T9 AI与非AI岗位的学历、经验构成（列内占比）
* -----------------------------------------------------------------------------
foreach pair in "edu_cat education" "exp_cat experience" {
    gettoken v label_name : pair
    local label_name = strtrim("`label_name'")
    preserve
    drop if missing(`v')
    contract ai_skill `v', freq(n)
    bysort ai_skill: egen double total = total(n)
    generate double share = n / total
    drop total
    export_table t9_composition_`label_name' "`tab'" "`xlsx'"
    restore
}

* -----------------------------------------------------------------------------
* 图
* -----------------------------------------------------------------------------
* F1 各年份AI岗位占比
preserve
import delimited using "`tab'/t3_by_year.csv", clear varnames(1) encoding("utf-8")
local lines ""
foreach v of local ai_vars {
    generate double pct_`v' = `v' * 100
    local lines "`lines' (connected pct_`v' year)"
}
quietly summarize year
local xl "`r(min)'(1)`r(max)'"
capture label variable pct_ai_skill "严格口径"
capture label variable pct_ai_skill_broad "宽泛口径"
capture label variable pct_ai_genai "生成式AI"
capture label variable pct_ai_traditional "传统AI"
twoway `lines', ytitle("占全部广告的比例（%）") xtitle("招聘发布年份") ///
    title("AI岗位占比") legend(rows(1)) xlabel(`xl')
export_graph f1_ai_share_by_year "`fig'"

* F4 各年份AI与非AI岗位平均对数工资
twoway (connected ln_wage_ai year) (connected ln_wage_nonai year), ///
    ytitle("平均对数月薪") xtitle("招聘发布年份") title("AI与非AI岗位的平均对数工资") ///
    legend(order(1 "AI岗位" 2 "非AI岗位") rows(1)) xlabel(`xl')
export_graph f4_ln_wage_by_year "`fig'"
restore

* F2 各月AI岗位占比
preserve
import delimited using "`tab'/t4_by_month.csv", clear varnames(1) encoding("utf-8")
generate ym2 = monthly(ym, "YM")
format ym2 %tm
generate double pct_ai = ai_skill * 100
label variable pct_ai "AI岗位（严格口径）"
local genai_line ""
capture confirm variable ai_genai
if !_rc {
    generate double pct_genai = ai_genai * 100
    label variable pct_genai "生成式AI"
    local genai_line "(line pct_genai ym2)"
}
twoway (line pct_ai ym2) `genai_line', ytitle("占当月广告的比例（%）") xtitle("招聘发布月份") ///
    title("各月AI岗位占比") xline(`=tm(2022m11)', lpattern(dash)) ///
    note("虚线：2022年11月ChatGPT发布") legend(rows(1))
export_graph f2_ai_share_by_month "`fig'"
restore

* F3 对数工资分布
twoway (kdensity ln_wage if ai_skill == 1) (kdensity ln_wage if ai_skill == 0), ///
    ytitle("密度") xtitle("对数月薪") title("AI与非AI岗位的工资分布") ///
    legend(order(1 "AI岗位" 2 "非AI岗位") rows(1))
export_graph f3_ln_wage_density "`fig'"

* -----------------------------------------------------------------------------
* 关键数字写进日志，便于复核
* -----------------------------------------------------------------------------
quietly count
display "DESC_SAMPLE_ROWS=" r(N)
quietly summarize ai_skill
display "AI_SHARE=" %6.4f r(mean)
quietly summarize ln_wage_ai
local m1 = r(mean)
quietly summarize ln_wage_nonai
display "RAW_LN_WAGE_GAP=" %6.4f (`m1' - r(mean))
display "STATA_TASK=PASS"
log close desc
