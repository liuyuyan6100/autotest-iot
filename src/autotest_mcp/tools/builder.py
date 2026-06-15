"""Builder：编译固件，产出 .bin / .elf / flash_args。

backend:
- docker（默认）：docker run --rm espressif/idf:<tag>，源码挂进 /project。
  先 set-target 再 build，两条用 shell && 串联。
- local：直接在宿主调 idf.py build（要求 IDF 环境已激活；Windows 上 IDF 已装时可用）。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable


def _find_artifacts(build_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    bins = list(build_dir.glob("*.bin"))
    elfs = list(build_dir.glob("*.elf"))
    flash_args = build_dir / "flash_args"
    if bins:
        app = [b for b in bins if "bootloader" not in b.name and "partition" not in b.name]
        out["bin_path"] = str(app[0] if app else bins[0])
    if elfs:
        out["elf_path"] = str(elfs[0])
    if flash_args.exists():
        out["flash_args_path"] = str(flash_args)
    return out


def _docker_shell_cmd(src: Path, idf_version: str, target: str) -> str:
    return (
        f"docker run --rm -v {src}:/project -w /project "
        f"espressif/idf:{idf_version} idf.py set-target {target} "
        f"&& docker run --rm -v {src}:/project -w /project "
        f"espressif/idf:{idf_version} idf.py build"
    )


def build(
    source_dir: str,
    idf_version: str = "v5.3",
    target: str = "esp32s3",
    backend: str = "docker",
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,  # type: ignore[assignment]
) -> dict[str, Any]:
    src = Path(source_dir).resolve()
    if not src.is_dir():
        return {"ok": False, "error": f"source dir not found: {src}"}

    start = time.monotonic()
    if backend == "docker":
        res = run(
            _docker_shell_cmd(src, idf_version, target),
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(src),
        )  # type: ignore[misc]
    else:
        res = run(["idf.py", "build"], capture_output=True, text=True, cwd=str(src))  # type: ignore[misc]

    build_dir = src / "build"
    result: dict[str, Any] = {
        "ok": res.returncode == 0,
        "duration_s": round(time.monotonic() - start, 3),
        "returncode": res.returncode,
        "build_log_tail": (res.stdout or "")[-2000:].strip(),
        "stderr_tail": (res.stderr or "")[-1000:].strip(),
    }
    result.update(_find_artifacts(build_dir))
    return result
