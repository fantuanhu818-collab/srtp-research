"""在1080条人工复核样本上回测occupation V4。

该回测是“已知错误回归测试”，不是独立样本准确率估计。V4通过后仍需新抽样本验证。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from occupation_v04 import (
    MANUAL_ADJUDICATION_PATH,
    MANUAL_GOLD_PATH,
    VERSION,
    build_classifier,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
DETAIL_PATH = QC_ROOT / "occupation_v04_manual_backtest.csv"
SUMMARY_PATH = QC_ROOT / "occupation_v04_manual_backtest_summary.csv"
ALIAS_AUDIT_PATH = QC_ROOT / "occupation_v04_manual_alias_audit.csv"
REPORT_PATH = QC_ROOT / "occupation_v04_manual_backtest_report.md"


def load_context(gold: pd.DataFrame) -> pd.DataFrame:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    parts = []
    for year, group in gold.groupby("year", sort=True):
        ids = group["source_record_id"].astype(str).tolist()
        path = Path(storage["curated_root"]) / "cleaned_v1" / f"jobs_{int(year)}_cleaned.parquet"
        dataset = ds.dataset(path, format="parquet")
        table = dataset.to_table(
            columns=["来源记录ID", "招聘岗位", "初级分类", "职位描述"],
            filter=ds.field("来源记录ID").isin(ids),
        )
        frame = table.to_pandas().rename(columns={
            "来源记录ID": "source_record_id",
            "招聘岗位": "source_job_title",
            "初级分类": "primary_category_raw",
            "职位描述": "job_description_raw",
        })
        parts.append(frame)
    context = pd.concat(parts, ignore_index=True)
    context["source_record_id"] = context["source_record_id"].astype(str)
    if context["source_record_id"].duplicated().any():
        raise RuntimeError("人工复核样本回溯职位描述时出现重复来源记录ID")
    missing = set(gold["source_record_id"].astype(str)) - set(context["source_record_id"])
    if missing:
        raise RuntimeError(f"有{len(missing)}条人工复核记录无法回溯到底表")
    return context


def accuracy(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main() -> int:
    QC_ROOT.mkdir(parents=True, exist_ok=True)
    gold = pd.read_csv(MANUAL_GOLD_PATH, dtype="string").fillna("")
    adjudication = pd.read_csv(MANUAL_ADJUDICATION_PATH, dtype="string").fillna("")
    adjudication_status = adjudication.set_index("source_record_id")["adjudication_status"]
    gold.loc[gold["source_record_id"].isin(adjudication_status.index), "manual_status"] = (
        gold.loc[gold["source_record_id"].isin(adjudication_status.index), "source_record_id"]
        .map(adjudication_status)
    )
    gold["year"] = pd.to_numeric(gold["year"], errors="raise").astype("int16")
    if len(gold) != 1080 or gold["source_record_id"].duplicated().any():
        raise RuntimeError("人工复核金标准行数或主键异常")

    context = load_context(gold)
    frame = gold.merge(context, on="source_record_id", how="left", validate="one_to_one")
    classifier = build_classifier()
    predictions = []
    for row in frame.itertuples(index=False):
        result = classifier.classify(
            str(row.job_title_raw), str(row.job_description_raw), str(row.primary_category_raw)
        )
        predictions.append({f"v04_{key}": value for key, value in result.items()})
    predicted = pd.DataFrame(predictions)
    detail = pd.concat([frame.reset_index(drop=True), predicted], axis=1)
    detail["v03_code_correct"] = (
        detail["v03_occupation_id"] == detail["manual_final_occupation_id"]
    ).astype("int8")
    detail["v04_code_correct"] = (
        detail["v04_occupation_id"] == detail["manual_final_occupation_id"]
    ).astype("int8")
    detail["v04_name_correct"] = (
        detail["v04_occupation_standard_name"] == detail["manual_final_standard_name"]
    ).astype("int8")
    detail["description_excerpt"] = detail["job_description_raw"].astype(str).str.slice(0, 240)

    confirmed = detail[detail["manual_status"].eq("confirmed")].copy()
    unresolved = detail[detail["manual_status"].eq("unresolved_z99")].copy()
    pending = detail[detail["manual_status"].eq("pending_conflict")].copy()

    summary_rows = [
        {
            "metric": "confirmed_records",
            "value": len(confirmed),
            "denominator": len(detail),
            "rate": accuracy(len(confirmed), len(detail)),
        },
        {
            "metric": "v03_code_accuracy_confirmed",
            "value": int(confirmed["v03_code_correct"].sum()),
            "denominator": len(confirmed),
            "rate": accuracy(int(confirmed["v03_code_correct"].sum()), len(confirmed)),
        },
        {
            "metric": "v04_code_accuracy_confirmed",
            "value": int(confirmed["v04_code_correct"].sum()),
            "denominator": len(confirmed),
            "rate": accuracy(int(confirmed["v04_code_correct"].sum()), len(confirmed)),
        },
        {
            "metric": "v04_name_accuracy_confirmed",
            "value": int(confirmed["v04_name_correct"].sum()),
            "denominator": len(confirmed),
            "rate": accuracy(int(confirmed["v04_name_correct"].sum()), len(confirmed)),
        },
        {
            "metric": "v04_z99_confirmed",
            "value": int(confirmed["v04_occupation_id"].eq("Z99").sum()),
            "denominator": len(confirmed),
            "rate": accuracy(int(confirmed["v04_occupation_id"].eq("Z99").sum()), len(confirmed)),
        },
        {
            "metric": "pending_conflict_records",
            "value": len(pending),
            "denominator": len(detail),
            "rate": accuracy(len(pending), len(detail)),
        },
        {
            "metric": "unresolved_z99_records",
            "value": len(unresolved),
            "denominator": len(detail),
            "rate": accuracy(len(unresolved), len(detail)),
        },
    ]
    summary = pd.DataFrame(summary_rows)

    detail_columns = [
        "source_record_id", "review_sequence", "review_group", "year", "review_stratum",
        "job_title_raw", "job_title_normalized_v03", "primary_category_raw",
        "v03_occupation_id", "v03_match_target", "manual_judgment_stage1",
        "manual_error_reason", "manual_final_standard_name", "manual_final_occupation_id",
        "manual_status", "supplement_status", "supplement_confidence",
        "v04_job_title_normalized", "v04_occupation_standard_name", "v04_occupation_id",
        "v04_occupation_name", "v04_occupation_method", "v04_occupation_rule_id",
        "v04_occupation_confidence", "v04_occupation_status", "v04_occupation_review_flag",
        "v04_occupation_score_top1", "v04_occupation_score_top2", "v04_occupation_score_margin",
        "v03_code_correct", "v04_code_correct", "v04_name_correct", "description_excerpt",
    ]
    detail[detail_columns].to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    pd.DataFrame(classifier.manual_alias_audit).to_csv(
        ALIAS_AUDIT_PATH, index=False, encoding="utf-8-sig"
    )

    error_summary = (
        confirmed.groupby("manual_error_reason", dropna=False)
        .agg(records=("source_record_id", "size"), v04_correct=("v04_code_correct", "sum"))
        .reset_index()
    )
    error_summary["accuracy"] = error_summary["v04_correct"] / error_summary["records"]
    method_counts = Counter(confirmed["v04_occupation_method"].tolist())
    wrong = confirmed.loc[confirmed["v04_code_correct"].eq(0), [
        "source_record_id", "job_title_raw", "manual_final_occupation_id",
        "v04_occupation_id", "v04_occupation_method", "v04_occupation_rule_id",
    ]]

    lines = [
        "# occupation V4人工样本回测报告",
        "",
        f"版本：`{VERSION}`",
        "",
        "> 本报告是已知错误的回归测试，不是独立样本准确率估计。",
        "",
        "## 核心结果",
        "",
        f"- 可确认金标准：{len(confirmed):,}条；",
        f"- V3代码准确：{int(confirmed['v03_code_correct'].sum()):,}/{len(confirmed):,}（{confirmed['v03_code_correct'].mean():.2%}）；",
        f"- V4代码准确：{int(confirmed['v04_code_correct'].sum()):,}/{len(confirmed):,}（{confirmed['v04_code_correct'].mean():.2%}）；",
        f"- V4仍错误：{len(wrong):,}条；",
        f"- 待裁决冲突：{len(pending):,}条；",
        f"- 确实无法判断并保留Z99：{len(unresolved):,}条。",
        "",
        "## V4方法分布",
        "",
        "|方法|条数|",
        "|---|---:|",
    ]
    lines.extend(f"|{method}|{count:,}|" for method, count in sorted(method_counts.items()))
    lines.extend([
        "",
        "## 按原错误原因检查",
        "",
        "|原错误原因|条数|V4正确|准确率|",
        "|---|---:|---:|---:|",
    ])
    for row in error_summary.itertuples(index=False):
        reason = row.manual_error_reason or "原判断正确"
        lines.append(f"|{reason}|{int(row.records):,}|{int(row.v04_correct):,}|{row.accuracy:.2%}|")
    if not wrong.empty:
        lines.extend([
            "",
            "## 仍未通过的记录",
            "",
            "|来源记录ID|岗位名称|人工代码|V4代码|方法|规则|",
            "|---|---|---|---|---|---|",
        ])
        for row in wrong.itertuples(index=False):
            lines.append(
                f"|{row.source_record_id}|{row.job_title_raw}|{row.manual_final_occupation_id}|"
                f"{row.v04_occupation_id}|{row.v04_occupation_method}|{row.v04_occupation_rule_id}|"
            )
    lines.extend([
        "",
        "## 下一道闸门",
        "",
        "V4通过本回归测试后，必须从未参与本轮规则开发的数据中重新分层抽样，",
        "人工检查后才能报告独立样本准确率并决定是否跑全量。",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"OCCUPATION_V04_GOLD={len(confirmed)}")
    print(f"OCCUPATION_V04_V3_ACCURACY={confirmed['v03_code_correct'].mean():.6f}")
    print(f"OCCUPATION_V04_V4_ACCURACY={confirmed['v04_code_correct'].mean():.6f}")
    print(f"OCCUPATION_V04_WRONG={len(wrong)}")
    print(f"OCCUPATION_V04_PENDING={len(pending)}")
    print(f"OCCUPATION_V04_REPORT={REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

