"""Verify that the SRTP project uses D-drive storage and temporary paths."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(r"D:\SRTP")
EXPECTED = {
    "SRTP_PROJECT_ROOT": PROJECT_ROOT,
    "SRTP_RAW_ROOT": DATA_ROOT / "分年份保存数据",
    "TEMP": DATA_ROOT / "工作数据" / "temp" / "python",
    "TMP": DATA_ROOT / "工作数据" / "temp" / "python",
    "UV_CACHE_DIR": DATA_ROOT / "工作数据" / "temp" / "uv",
    "STATATMP": DATA_ROOT / "工作数据" / "temp" / "stata",
    "SRTP_DUCKDB_TEMP": DATA_ROOT / "工作数据" / "temp" / "duckdb",
}


def normalized(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def require_equal(label: str, actual: str | Path, expected: str | Path) -> None:
    if normalized(actual) != normalized(expected):
        raise RuntimeError(f"{label}不正确：{actual}；应为：{expected}")


def main() -> None:
    if sys.version_info.releaselevel != "final":
        raise RuntimeError(f"项目Python不是稳定版：{sys.version}")
    require_equal("Python解释器", sys.executable, PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")

    for name, expected_path in EXPECTED.items():
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"缺少环境变量：{name}")
        require_equal(name, value, expected_path)
        expected_path.mkdir(parents=True, exist_ok=True)

    require_equal("Python临时目录", tempfile.gettempdir(), EXPECTED["TEMP"])

    duckdb_temp = os.environ["SRTP_DUCKDB_TEMP"].replace("\\", "/")
    connection = duckdb.connect()
    try:
        escaped_temp = duckdb_temp.replace("'", "''")
        connection.execute(f"SET temp_directory = '{escaped_temp}'")
        configured_temp = connection.execute(
            "SELECT current_setting('temp_directory')"
        ).fetchone()[0]
    finally:
        connection.close()
    require_equal("DuckDB临时目录", configured_temp, EXPECTED["SRTP_DUCKDB_TEMP"])

    print("STORAGE_ENVIRONMENT_GATE=PASS")
    print(f"python={sys.executable}")
    print(f"python_temp={tempfile.gettempdir()}")
    print(f"uv_cache={os.environ['UV_CACHE_DIR']}")
    print(f"duckdb_temp={configured_temp}")
    print(f"stata_temp={os.environ['STATATMP']}")
    print(f"raw_data={os.environ['SRTP_RAW_ROOT']}")


if __name__ == "__main__":
    main()
