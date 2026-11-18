"""将经独立人工反馈修订的V4.1职业分类应用到2018—2025年全样本。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from occupation_v04 import VERSION, build_classifier, normalize_title_v04


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
RULE_PATH = PROJECT_ROOT / "config" / "occupation_rule_overrides_v0.4.json"
VALIDATION_PATH = PROJECT_ROOT / "config" / "occupation_independent_validation_v0.4.csv"
YEARS = range(2018, 2026)
BATCH_SIZE = 100_000
QC_ROOT = PROJECT_ROOT / "outputs" / "qc"
ANNUAL_PATH = QC_ROOT / "occupation_v041_all_years_annual.csv"
DISTRIBUTION_PATH = QC_ROOT / "occupation_v041_all_years_distribution.csv"
TRANSITION_PATH = QC_ROOT / "occupation_v041_vs_v03_transition.csv"
UNCLASSIFIED_PATH = QC_ROOT / "occupation_v041_top_unclassified.csv"
REPORT_PATH = QC_ROOT / "occupation_v041_all_years_report.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def load_context_descriptions(cleaned_path: Path, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    found: dict[str, str] = {}
    scanner = ds.dataset(cleaned_path, format="parquet").scanner(
        columns=["来源记录ID", "职位描述"], batch_size=BATCH_SIZE
    )
    for batch in scanner.to_batches():
        part = batch.to_pandas()
        part["来源记录ID"] = part["来源记录ID"].astype(str)
        part = part.loc[part["来源记录ID"].isin(ids)]
        if not part.empty:
            found.update(zip(part["来源记录ID"], part["职位描述"].fillna("").astype(str)))
    missing = ids - set(found)
    if missing:
        raise RuntimeError(f"清洗表缺少{len(missing)}条上下文记录")
    return found


def main() -> int:
    storage = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    output_root = Path(storage["features_root"]) / "occupation_v0.4.1"
    output_root.mkdir(parents=True, exist_ok=True)
    classifier = build_classifier()

    annual_rows: list[dict] = []
    distribution_rows: list[dict] = []
    transition_rows: list[dict] = []
    all_unclassified: Counter[tuple[str, str]] = Counter()

    for year in YEARS:
        v03_path = Path(storage["features_root"]) / "occupation_v0.3" / f"jobs_{year}_occupation_v0.3.parquet"
        cleaned_path = Path(storage["curated_root"]) / "cleaned_v1" / f"jobs_{year}_cleaned.parquet"
        output_path = output_root / f"jobs_{year}_occupation_v0.4.1.parquet"
        if not v03_path.exists() or not cleaned_path.exists():
            raise FileNotFoundError(f"{year}年输入缺失")

        source = pq.read_table(v03_path, columns=[
            "source_record_id", "job_title_raw", "occupation_id", "occupation_name",
        ]).to_pandas()
        source["source_record_id"] = source["source_record_id"].astype(str)
        source["job_title_raw"] = source["job_title_raw"].fillna("").astype(str)
        source["v03_occupation_id"] = source.pop("occupation_id").fillna("Z99").astype(str)
        source["v03_occupation_name"] = source.pop("occupation_name").fillna("").astype(str)
        if source["source_record_id"].duplicated().any():
            raise RuntimeError(f"{year}年V3主键重复")

        unique_raw = source["job_title_raw"].drop_duplicates()
        raw_to_normalized = {raw: normalize_title_v04(raw) for raw in unique_raw}
        source["job_title_normalized"] = source["job_title_raw"].map(raw_to_normalized)
        unique_normalized = source["job_title_normalized"].drop_duplicates().tolist()
        base_results = {
            title: classifier.classify(title, "", "") for title in unique_normalized
        }

        description_rules = [rule for rule in classifier.context_rules if rule["description_re"] is not None]
        context_titles = {
            title for title in unique_normalized
            if any(rule["title_re"].search(title) for rule in description_rules)
        }
        context_rows = source.loc[source["job_title_normalized"].isin(context_titles), [
            "source_record_id", "job_title_normalized"
        ]]
        context_ids = set(context_rows["source_record_id"])
        descriptions = load_context_descriptions(cleaned_path, context_ids)
        context_overrides: dict[str, dict] = {}
        for row in context_rows.itertuples(index=False):
            context = classifier._match_context(
                row.job_title_normalized, descriptions[row.source_record_id]
            )
            if context is None:
                continue
            result = classifier._result(
                context["occupation_id"], context["standard_name"], "context_rule",
                context["rule_id"], context["confidence"], "context_classified",
                row.job_title_normalized,
                review_flag=int(context["confidence"] != "high"),
            )
            base = base_results[row.job_title_normalized]
            if any(result[key] != base[key] for key in [
                "occupation_id", "occupation_standard_name", "occupation_rule_id"
            ]):
                context_overrides[row.source_record_id] = result

        temp_path = output_path.with_suffix(".parquet.tmp")
        temp_path.unlink(missing_ok=True)
        writer: pq.ParquetWriter | None = None
        year_methods: Counter[str] = Counter()
        year_distribution: Counter[tuple[str, str, str, str]] = Counter()
        year_transitions: Counter[tuple[str, str]] = Counter()
        classified = 0
        changed = 0
        total_written = 0
        try:
            for start in range(0, len(source), BATCH_SIZE):
                part = source.iloc[start:start + BATCH_SIZE].reset_index(drop=True)
                results = [
                    context_overrides.get(record_id, base_results[title])
                    for record_id, title in zip(part["source_record_id"], part["job_title_normalized"])
                ]
                predicted = pd.DataFrame(results)
                output = pd.concat([
                    part[["source_record_id", "job_title_raw", "v03_occupation_id", "v03_occupation_name"]],
                    predicted,
                ], axis=1)
                output = output[[
                    "source_record_id", "job_title_raw", "job_title_normalized",
                    "occupation_l1", "occupation_l1_name", "occupation_id", "occupation_name",
                    "occupation_standard_name", "occupation_method", "occupation_rule_id",
                    "occupation_confidence", "occupation_status", "occupation_review_flag",
                    "occupation_score_top1", "occupation_score_top2", "occupation_score_margin",
                    "occupation_version", "v03_occupation_id", "v03_occupation_name",
                ]]
                output["occupation_review_flag"] = output["occupation_review_flag"].astype("int8")
                for column in ["occupation_score_top1", "occupation_score_top2", "occupation_score_margin"]:
                    output[column] = output[column].astype("float32")
                table = pa.Table.from_pandas(output, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(temp_path, table.schema, compression="zstd")
                writer.write_table(table)

                total_written += len(output)
                classified += int(output["occupation_id"].ne("Z99").sum())
                changed += int(output["occupation_id"].ne(output["v03_occupation_id"]).sum())
                year_methods.update(output["occupation_method"].tolist())
                year_distribution.update(zip(
                    output["occupation_l1"], output["occupation_l1_name"],
                    output["occupation_id"], output["occupation_name"],
                ))
                year_transitions.update(zip(output["v03_occupation_id"], output["occupation_id"]))
                z99 = output.loc[output["occupation_id"].eq("Z99")]
                all_unclassified.update(zip(z99["job_title_normalized"], z99["occupation_status"]))
        finally:
            if writer is not None:
                writer.close()

        if total_written != len(source):
            raise RuntimeError(f"{year}年输出行数不一致")
        os.replace(temp_path, output_path)
        metadata_rows = pq.ParquetFile(output_path).metadata.num_rows
        if metadata_rows != len(source):
            raise RuntimeError(f"{year}年Parquet行数校验失败")

        annual_rows.append({
            "year": year,
            "records": len(source),
            "classified": classified,
            "classified_share": classified / len(source),
            "z99": len(source) - classified,
            "changed_from_v03": changed,
            "changed_share": changed / len(source),
            "context_sensitive_rows": len(context_rows),
            "context_overrides": len(context_overrides),
            "output_path": str(output_path),
            "output_sha256": sha256(output_path),
        })
        for (l1, l1_name, code, name), count in year_distribution.items():
            distribution_rows.append({
                "year": year, "occupation_l1": l1, "occupation_l1_name": l1_name,
                "occupation_id": code, "occupation_name": name,
                "count": count, "share": count / len(source),
            })
        for (old, new), count in year_transitions.items():
            transition_rows.append({
                "year": year, "v03_occupation_id": old, "v041_occupation_id": new,
                "count": count, "share": count / len(source),
            })
        print(
            f"YEAR_DONE={year};ROWS={len(source)};CLASSIFIED_SHARE={classified / len(source):.6f};"
            f"CHANGED_SHARE={changed / len(source):.6f};CONTEXT_OVERRIDES={len(context_overrides)}",
            flush=True,
        )

    annual = pd.DataFrame(annual_rows)
    distribution = pd.DataFrame(distribution_rows).sort_values(["year", "count"], ascending=[True, False])
    transitions = pd.DataFrame(transition_rows).sort_values(["year", "count"], ascending=[True, False])
    unclassified = pd.DataFrame([
        {"job_title_normalized": title, "occupation_status": status, "count": count}
        for (title, status), count in all_unclassified.most_common(500)
    ])
    write_csv(ANNUAL_PATH, annual)
    write_csv(DISTRIBUTION_PATH, distribution)
    write_csv(TRANSITION_PATH, transitions)
    write_csv(UNCLASSIFIED_PATH, unclassified)

    total = int(annual["records"].sum())
    total_classified = int(annual["classified"].sum())
    total_changed = int(annual["changed_from_v03"].sum())
    lines = [
        f"|{int(row.year)}|{int(row.records):,}|{int(row.classified):,}|{row.classified_share:.2%}|"
        f"{int(row.z99):,}|{int(row.changed_from_v03):,}|{row.changed_share:.2%}|"
        for row in annual.itertuples(index=False)
    ]
    REPORT_PATH.write_text(f"""# 2018—2025年 occupation V4.1 全量构建报告

## 总体结果

- 总记录：{total:,}条；
- 已归入37类：{total_classified:,}条，占{total_classified / total:.2%}；
- Z99：{total - total_classified:,}条，占{1 - total_classified / total:.2%}；
- 相比V3职业代码发生变化：{total_changed:,}条，占{total_changed / total:.2%}。

## 分年度结果

|年份|记录数|已分类|覆盖率|Z99|相对V3变化数|变化率|
|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

## 使用说明

1. V4.1吸收了1080条原分层复核和300条独立验证反馈；
2. 300条独立验证在修订前的职业代码准确率为90.33%，错误主要来自Z99未分类；
3. 新反馈用于修正规则后，该300条只能作为“反馈修复一致性检查”，不能再当作完全独立的准确率；
4. V4.1仍保留Z99，不用初级分类强行兜底；
5. 本批文件是独立职业特征表，没有覆盖清洗底表或V3结果。
""", encoding="utf-8")

    manifest = {
        "version": VERSION,
        "status": "validated_candidate_v041",
        "years": list(YEARS),
        "records": total,
        "classified": total_classified,
        "classified_share": total_classified / total,
        "changed_from_v03": total_changed,
        "rule_sha256": sha256(RULE_PATH),
        "validation_sha256": sha256(VALIDATION_PATH),
        "outputs": annual_rows,
    }
    (output_root / "manifest_all_years.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"TOTAL_ROWS={total}")
    print(f"CLASSIFIED_SHARE={total_classified / total:.6f}")
    print(f"CHANGED_FROM_V03={total_changed}")
    print(f"OUTPUT_ROOT={output_root}")
    print("OCCUPATION_V041_ALL_YEARS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
