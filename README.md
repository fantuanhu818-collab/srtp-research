# SRTP科研数据分析项目

本目录保存可以由Git管理的程序、研究规则、说明文档和小型结果。大型数据与答辩材料保存在`D:\SRTP`，不进入Git仓库。

## 目录

```text
code/       Stata与SQL程序
config/     路径示例和项目配置
docs/       工作流、分工和研究说明
outputs/    小型审计、表格和图形
scripts/    Python程序和运行工具
```

本机实际路径保存在`config/storage_paths.json`。该文件不会上传GitHub；其他电脑应复制`config/storage_paths.example.json`并填写自己的路径。

B及其Codex首次接手项目时，请先阅读`docs/B的Codex项目说明.md`。

## 运行Python

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_python_task.ps1 `
  -ScriptPath scripts/任务名称.py
```

## 运行Stata

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_stata_task.ps1 `
  -DoFile code/stata/任务名称.do `
  -ExpectedLog outputs/analysis/任务名称.log
```

原始数据只能读取，不得由程序修改、移动、重命名或覆盖。
