# wage_fix_v4 独立复核报告

结论：通过。26项检查全部通过。v4 把低值段的日薪、时薪换算为月薪：10,649条中换算10,386条、置缺失263条；换算后全表不存在高于100,000元的月薪，也没有低于100元的记录（仅77条极小兼职换算后仍在千元以下）。

## 一、检查项

|检查项|预期|实际|结果|
|---|---|---|---|
|字段清单|source_record_id,wage_mid_orig,ln_wage_orig,wage_mid_fixed,ln_wage_fixed,wage_fix_flag,wage_fix_rule,wage_fix_factor,wage_fix_action,wage_fix_version|source_record_id,wage_mid_orig,ln_wage_orig,wage_mid_fixed,ln_wage_fixed,wage_fix_flag,wage_fix_rule,wage_fix_factor,wage_fix_action,wage_fix_version|通过|
|总行数|5,235,461|5,235,461|通过|
|source_record_id唯一数|5,235,461|5,235,461|通过|
|flag取值越界|0|0|通过|
|action取值越界|0|0|通过|
|月薪>100000的记录数|0|0|通过|
|月薪<1000的记录数（极小兼职换算后仍在千元以下）|77|77|通过|
|缺失记录数（v3的132条 + 本次263条）|395|395|通过|
|工资有但对数缺|0|0|通过|
|工资缺但对数有|0|0|通过|
|对数不等于ln(工资)|0|0|通过|
|flag=2但action不是缺失|0|0|通过|
|flag=1但action为none|0|0|通过|
|低值段条数|10,649|10,649|通过|
|极小值(≤10元)条数|261|261|通过|
|低值段中>10元被置缺失条数（换算后超10万）|2|2|通过|
|非低值段被改动|0|0|通过|
|非低值段标志被改动|0|0|通过|
|低值段置缺失但不符合规则|0|0|通过|
|低值段逐条重算条数|10,649|10,649|通过|
|规则标签与重算不一致|0|0|通过|
|缺失状态与重算不一致|0|0|通过|
|换算值与重算不一致|0|0|通过|
|年度分布与CSV不一致项|0|0|通过|
|对数偏度与manifest一致|0.158|0.158|通过|
|对数峰度与manifest一致|0.019|0.019|通过|

## 二、低值段换算规则与命中数

|规则|处理|命中条数|换算后中位|
|---|---|---:|---:|
|daily_to_monthly_by_magnitude|×21.75|6,787|2,436|
|hourly_to_monthly_by_magnitude|×174|1,295|4,350|
|error_div12_to_monthly|×12|1,015|1,440|
|hourly_to_monthly|×174|868|3,306|
|daily_to_monthly_by_text|×21.75|421|2,610|
|missing_tiny_value|置缺失|261||
|missing_over_cap|置缺失|2||

## 三、处理前后

|指标|v3|v4|
|---|---:|---:|
|有效记录|5,235,329|5,235,066|
|平均月薪|11,212.1|11,219.9|
|中位月薪|9,001.0|9,000.5|
|P1|2,500|2,500|
|P99|40,000|40,000|
|最小月薪|1|326|
|对数偏度|−0.753|0.158|
|对数峰度|7.244|0.019|

## 四、口径说明

- 判定顺序：①≤10元置缺失；②文本“元/小时”×174；③文本“元/天”×21.75；④2021平台28 ×12；⑤其余<60元×174、≥60元×21.75；
- 换算依据：日薪×21.75（法定月计薪天数）；时薪×8小时×21.75天=×174；
- 263条置缺失：261条为≤10元的占位/极小值，2条换算后超过10万元（平台77的800元记录，×174=13.9万）；
- 低值段以外5,224,812条记录与v3逐条一致；
- `wage_fix_action` 为新增列，取值 none/divide/multiply/set_missing；
- 逐条清单：`outputs/qc/wage_fix_v4_low_tail_resolved.csv`。

## 五、复现

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/47_build_wage_fix_v4.py
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 -ScriptPath code/python/48_validate_wage_fix_v4.py
```
