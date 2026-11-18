"""规则v0.2第4步：合并A、B独立填写的筛词表（方案第5.2节）。

分工（11-18折中方案）：
  重点词（单独出现≥100条广告，120个，占新增影响的98%）→ A、B都筛；
  其余280个影响小的词 → 按编号顺序交替分给A、B（第1个给A、第2个给B……），各140个，只由一人筛。
合并规则：
  重点词：两人都填1、2、3之一 → 加入，层级取更严的（1严格 > 2条件 > 3宽泛）；有一人填0 → 不加入。
  单人词：按负责人的结果；填0 → 不加入。
只在重点词上报告两人“加入/不加入”的一致率和Cohen's kappa，以及两人都加入时层级的一致率。
负责范围以外的格子即使填了也不使用（会报告条数）。

输入：<analysis_root>/ai_w2v_screening_v0.2/筛词表_A、筛词表_B（.xlsx或.csv，两人填好后放回原处，不改文件名）
输出（不进Git）：<analysis_root>/ai_w2v_screening_v0.2/合并结果.csv、分歧清单.csv
输出（无原文）：outputs/qc/ai_w2v_screening_v0.2_merged.csv、outputs/qc/ai_w2v_screening_v0.2_summary.json

运行：.venv/bin/python code/python/19_merge_screening.py
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QC_DIR = PROJECT_ROOT / "outputs" / "qc"
RESULT_COL = "筛选结果(1严格/2条件/3宽泛/0不加入)"
TIER = {"1": "strict", "2": "conditional", "3": "broad"}
KEY_MIN_ALONE = 100
ALONE_COL = "不含现有严格词的广告数"


def assignment(rows: list[dict]) -> dict[str, str]:
    """编号 → "AB"（重点词，两人都筛）/"A"/"B"（影响小的词，按编号顺序交替分配）。rows 需含编号和单独出现广告数。"""
    out, i = {}, 0
    for r in sorted(rows, key=lambda r: int(r["编号"])):
        if int(r[ALONE_COL]) >= KEY_MIN_ALONE:
            out[str(r["编号"])] = "AB"
        else:
            out[str(r["编号"])] = "AB"[i % 2]
            i += 1
    return out


def merge_one(a: str, b: str) -> str:
    """返回合并后的层级代码：'1'/'2'/'3'，或'0'表示不加入。"""
    if a == "0" or b == "0":
        return "0"
    return min(a, b)  # '1'最严


def cohen_kappa(x: list[int], y: list[int]) -> float | None:
    n = len(x)
    po = sum(i == j for i, j in zip(x, y)) / n
    pe = sum((x.count(c) / n) * (y.count(c) / n) for c in set(x) | set(y))
    return None if pe == 1 else (po - pe) / (1 - pe)


def _read_xlsx(path: Path) -> list[dict]:
    """读 22_screening_xlsx.py 生成的Excel：“筛词表”页第5行是表头，第6行起是数据，编号与CSV一致。"""
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True)["筛词表"]
    head = [str(c.value).split("\n")[0] if c.value else "" for c in ws[5]]
    idx = {name: head.index(name) for name in ("编号", "候选词", "来源组", "共现", "筛选结果", "备注")}
    rows = []
    for vals in ws.iter_rows(min_row=6, values_only=True):
        if vals[idx["编号"]] is None:
            continue
        v = vals[idx["筛选结果"]]
        v = "" if v is None else str(int(v)) if isinstance(v, (int, float)) else str(v).strip()
        rows.append({"编号": str(vals[idx["编号"]]), "候选词": str(vals[idx["候选词"]]),
                     "来源组": str(vals[idx["来源组"]]).replace("、", "|"), "共现相关度": vals[idx["共现"]] or "",
                     RESULT_COL: v, "备注": vals[idx["备注"]] or ""})
    return rows


def read_sheet(path: Path, who: str, assign: dict[str, str]) -> dict[str, dict]:
    """优先读Excel版；Excel版一行没填、CSV版有填写时读CSV版；两版都有填写则报错，避免混用。"""
    xlsx, csv_path = path.with_suffix(".xlsx"), path.with_suffix(".csv")
    filled = lambda rs: sum(bool(str(r[RESULT_COL]).strip()) for r in rs)  # noqa: E731
    x_rows = _read_xlsx(xlsx) if xlsx.exists() else []
    with csv_path.open(encoding="utf-8-sig") as f:
        c_rows = list(csv.DictReader(f))
    if filled(x_rows) and filled(c_rows):
        raise SystemExit(f"{xlsx.name} 和 {csv_path.name} 都有填写，请确认用哪一版后删除或改名另一版")
    use, src = (x_rows, xlsx) if filled(x_rows) else (c_rows, csv_path)
    print(f"READ {src.name}: {filled(use)}/{len(use)} 已填写")
    rows = {r["编号"]: r for r in use}
    path = src
    mine = {k for k, w in assign.items() if who in w}
    bad = [(k, r["候选词"], r[RESULT_COL]) for k, r in rows.items()
           if k in mine and r[RESULT_COL].strip() not in {"0", "1", "2", "3"}]
    if bad:
        raise SystemExit(f"{path.name} 负责的 {len(mine)} 个词中有 {len(bad)} 个未填或填写不是0/1/2/3，例如：{bad[:5]}")
    extra = sum(1 for k, r in rows.items() if k not in mine and r[RESULT_COL].strip())
    if extra:
        print(f"NOTE {path.name}: 负责范围以外填了 {extra} 个，不使用")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-config", type=Path, default=PROJECT_ROOT / "config" / "storage_paths.json")
    args = ap.parse_args()
    storage = json.loads(args.storage_config.read_text(encoding="utf-8"))
    sheet_dir = Path(storage["analysis_root"]) / "ai_w2v_screening_v0.2"
    with (sheet_dir / "筛词表_A.csv").open(encoding="utf-8-sig") as f:
        assign = assignment(list(csv.DictReader(f)))
    A, B = read_sheet(sheet_dir / "筛词表_A", "A", assign), read_sheet(sheet_dir / "筛词表_B", "B", assign)
    if set(A) != set(B) or set(A) != set(assign) or any(A[k]["候选词"] != B[k]["候选词"] for k in A):
        raise SystemExit("两份筛词表的编号或候选词不一致，请确认用的是同一版表格")

    merged, disagree = [], []
    for k in sorted(A, key=int):
        w = assign[k]
        a = A[k][RESULT_COL].strip() if "A" in w else ""
        b = B[k][RESULT_COL].strip() if "B" in w else ""
        m = merge_one(a, b) if w == "AB" else (a or b)
        row = {"编号": k, "候选词": A[k]["候选词"], "来源组": A[k]["来源组"], "共现相关度": A[k]["共现相关度"],
               "筛选方式": {"AB": "两人", "A": "仅A", "B": "仅B"}[w],
               "A": a, "B": b, "合并结果": m, "加入": int(m != "0"), "层级": TIER.get(m, ""),
               "A备注": A[k]["备注"] if "A" in w else "", "B备注": B[k]["备注"] if "B" in w else ""}
        merged.append(row)
        if w == "AB" and a != b:
            disagree.append(row)

    key = [r for r in merged if r["筛选方式"] == "两人"]
    inc_a = [int(r["A"] != "0") for r in key]
    inc_b = [int(r["B"] != "0") for r in key]
    both_in = [(r["A"], r["B"]) for r in key if r["A"] != "0" and r["B"] != "0"]
    kappa = cohen_kappa(inc_a, inc_b)
    summary = {
        "n_candidates": len(merged),
        "design": "重点词（单独出现≥100条）两人都筛；其余按编号交替分给A、B，单人筛",
        "n_double_coded": len(key),
        "n_single_A": sum(r["筛选方式"] == "仅A" for r in merged),
        "n_single_B": sum(r["筛选方式"] == "仅B" for r in merged),
        "key_include_agreement": round(sum(i == j for i, j in zip(inc_a, inc_b)) / len(key), 4),
        "key_include_kappa": None if kappa is None else round(kappa, 4),
        "key_tier_agreement_when_both_include": round(sum(a == b for a, b in both_in) / len(both_in), 4) if both_in else None,
        "key_n_include_A": sum(inc_a), "key_n_include_B": sum(inc_b),
        "merged_tiers": Counter(r["层级"] or "not_added" for r in merged),
        "merged_tiers_double_coded": Counter(r["层级"] or "not_added" for r in key),
        "n_disagreements_key": len(disagree),
    }

    def write(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
        cols = cols or list(rows[0])
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    write(sheet_dir / "合并结果.csv", merged)
    write(sheet_dir / "分歧清单.csv", disagree, list(merged[0]))  # 只含重点词
    write(QC_DIR / "ai_w2v_screening_v0.2_merged.csv", merged,
          ["编号", "候选词", "来源组", "共现相关度", "筛选方式", "A", "B", "合并结果", "加入", "层级"])
    (QC_DIR / "ai_w2v_screening_v0.2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
