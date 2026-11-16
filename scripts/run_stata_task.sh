#!/usr/bin/env bash
# Mac版Stata运行工具，对应 scripts/run_stata_task.ps1。
# 用法：scripts/run_stata_task.sh <do文件> <预期日志> [传给do文件的参数...]
# 例：  scripts/run_stata_task.sh code/stata/20_descriptive_stats.do \
#         outputs/analysis/descriptive_2022/descriptive_stats.log \
#         "/path/analysis_2022.dta" "outputs/analysis/descriptive_2022" 2022
# 只有Stata生成了本次的新日志且日志含 STATA_TASK=PASS 才算成功。
set -euo pipefail

do_file="$1"; expected_log="$2"; shift 2
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

stata_exe="${STATA_EXE:-}"
if [[ -z "$stata_exe" ]]; then
  for c in /Applications/Stata*/Stata*.app/Contents/MacOS/stata-* ; do
    [[ -x "$c" ]] && stata_exe="$c" && break
  done
fi
[[ -x "$stata_exe" ]] || { echo "找不到Stata，可设置环境变量 STATA_EXE" >&2; exit 1; }

mkdir -p "$(dirname "$expected_log")" logs
marker="$(mktemp)"
# Stata把命令行各词直接拼成一条命令，含空格的路径必须自带引号。
# 在项目根目录运行，do文件中的相对路径以项目根目录为准；批处理日志随后移到 logs/。
stata_args=()
for a in "$@"; do stata_args+=("\"$a\""); done
"$stata_exe" -b do "\"$do_file\"" "${stata_args[@]}" || true

batch_name="$(basename "${do_file%.do}").log"
batch_log="logs/$batch_name"
[[ -f "$batch_name" ]] && mv -f "$batch_name" "$batch_log"
if [[ ! -f "$expected_log" || "$expected_log" -ot "$marker" ]]; then
  echo "没有生成本次的日志：$expected_log；查看批处理日志：$batch_log" >&2
  tail -20 "$batch_log" >&2 || true
  exit 1
fi
if ! grep -q "STATA_TASK=PASS" "$expected_log"; then
  echo "日志中没有 STATA_TASK=PASS：$expected_log" >&2
  tail -20 "$batch_log" >&2 || true
  exit 1
fi
rm -f "$marker"
echo "STATA_TASK=PASS"
