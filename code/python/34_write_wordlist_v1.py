"""生成v1.0词典的人读版词表 docs/AI技能词典_v1.0_词表.md（11-19）。

沿用 20_build_dictionary_v0.2.py 的格式，另加v1.0（§8微调一轮）的改动记录。
用法：.venv/bin/python code/python/34_write_wordlist_v1.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "config" / "ai_skill_dictionary_v1.0.json"
OUT = ROOT / "docs" / "AI技能词典_v1.0_词表.md"

mod_spec = importlib.util.spec_from_file_location("b20", ROOT / "code" / "python" / "20_build_dictionary_v0.2.py")
b20 = importlib.util.module_from_spec(mod_spec)
mod_spec.loader.exec_module(b20)


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    b20.READABLE = OUT
    b20.write_readable(spec)
    text = OUT.read_text(encoding="utf-8")
    text = text.replace("`code/python/20_build_dictionary_v0.2.py` 自动生成", "`code/python/34_write_wordlist_v1.py` 自动生成")
    text = text.replace("`config/ai_skill_dictionary_v0.2_draft.json`", "`config/ai_skill_dictionary_v1.0.json`（终版，已冻结）")
    log = spec["changelog_v1.0"]
    lines = ["## v1.0改动记录（§8微调一轮，2026-11-18）", "",
             f"- 依据：{log['basis']}",
             f"- 规则3：{log['rule3_delete_new_terms']['trigger']} → {log['rule3_delete_new_terms']['action']}，"
             f"共{len(log['rule3_delete_new_terms']['terms'])}个：" + "、".join(f"`{t}`" for t in log["rule3_delete_new_terms"]["terms"]),
             f"- 规则1：{log['rule1_demote']['trigger']} → {log['rule1_demote']['action']}：" + "、".join(f"`{t}`" for t in log["rule1_demote"]["terms"]),
             f"  - {log['rule1_demote']['tie_note']}",
             f"- 未触发：{log['not_triggered']}",
             f"- 报告口径：{log['report']}", ""]
    OUT.write_text(text + "\n".join(lines), encoding="utf-8")
    print(f"-> {OUT}")
    print("PYTHON_TASK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
