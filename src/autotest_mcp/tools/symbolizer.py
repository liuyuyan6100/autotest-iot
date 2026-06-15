"""Symbolizer：把 panic backtrace 的裸地址还原成 函数+文件:行。

依赖 ESP-IDF 工具链的 xtensa-esp32s3-elf-addr2line。addr2line 路径可显式配置，
否则从 PATH / $IDF_PATH 自动发现。coredump 走 espcoredump.py（M0 先支持 backtrace 文本）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{8,}")
_ADDR2LINE_CANDIDATES = (
    "xtensa-esp32s3-elf-addr2line",
    "xtensa-esp-elf-addr2line",
    "esp-elf-addr2line",
)


def extract_addresses(text: str) -> list[str]:
    """优先取 Backtrace: 行里的地址；没有则回退到全文所有长十六进制。"""
    addrs: list[str] = []
    for line in text.splitlines():
        if "backtrace" in line.lower():
            addrs.extend(_ADDR_RE.findall(line))
    if not addrs:
        addrs = _ADDR_RE.findall(text)
    seen: set[str] = set()
    out: list[str] = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def find_addr2line(configured: str = "") -> str | None:
    if configured:
        p = shutil.which(configured) or (configured if Path(configured).exists() else None)
        if p:
            return p
    for name in _ADDR2LINE_CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    idf_path = os.environ.get("IDF_PATH")
    if idf_path:
        root = Path(idf_path) / "tools"
        hits = list(root.rglob("xtensa-esp32s3-elf-addr2line"))
        if hits:
            return str(hits[0])
    return None


def symbolize(
    elf_path: str,
    text: str,
    addr2line: str | None = None,
    run=subprocess.run,  # type: ignore[assignment]
) -> dict[str, Any]:
    addrs = extract_addresses(text)
    if not addrs:
        return {"symbolized": "", "addresses_found": 0, "error": "no addresses found in input"}

    bin_path = addr2line or find_addr2line()
    if not bin_path or not (Path(bin_path).exists() or shutil.which(bin_path)):
        return {
            "symbolized": "",
            "addresses_found": len(addrs),
            "error": "addr2line not found; set tools.addr2line or install ESP-IDF toolchain",
        }
    if not Path(elf_path).exists():
        return {
            "symbolized": "",
            "addresses_found": len(addrs),
            "error": f"elf not found: {elf_path}",
        }

    cmd = [bin_path, "-pfiaC", "-e", elf_path, *addrs]
    res = run(cmd, capture_output=True, text=True, timeout=30)  # type: ignore[misc]
    return {
        "symbolized": (res.stdout or "").strip(),
        "addresses_found": len(addrs),
        "returncode": res.returncode,
        "stderr": (res.stderr or "").strip(),
    }
