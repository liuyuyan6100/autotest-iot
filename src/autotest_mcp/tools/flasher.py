"""Flasher：esptool 烧录。

两种模式：
- 单镜像：传 .bin 路径，write_flash 0x0。
- 从 build 目录：传含 flash_args 的目录，write_flash @flash_args（自动处理 bootloader/partition/app 偏移，最稳）。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _esptool_cmd(port: str, baud: int) -> list[str]:
    return [sys.executable, "-m", "esptool", "--port", port, "--baud", str(baud), "write_flash"]


def flash(
    port: str,
    baud: int,
    bin_or_build_dir: str,
    *,
    run=subprocess.run,  # type: ignore[assignment]
) -> dict[str, Any]:
    target = Path(bin_or_build_dir)
    flash_args = target / "flash_args" if target.is_dir() else None

    if target.is_file() and target.suffix == ".bin":
        cmd = _esptool_cmd(port, baud) + ["0x0", str(target)]
    elif flash_args and flash_args.exists():
        cmd = _esptool_cmd(port, baud) + [f"@{flash_args}"]
    else:
        return {
            "ok": False,
            "error": "need a .bin file or a build dir containing flash_args",
        }

    start = time.monotonic()
    res = run(cmd, capture_output=True, text=True)  # type: ignore[misc]
    return {
        "ok": res.returncode == 0,
        "duration_s": round(time.monotonic() - start, 3),
        "returncode": res.returncode,
        "stdout": (res.stdout or "").strip(),
        "stderr": (res.stderr or "").strip(),
        "command": cmd,
    }
