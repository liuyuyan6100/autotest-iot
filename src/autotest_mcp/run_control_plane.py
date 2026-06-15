"""控制面 server CLI：起 VPS 常驻唯一入口。

  python -m autotest_mcp.run_control_plane
  # token 从 AUTOTEST_CP_TOKEN 或 config control_plane.token
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import load_config
from .control_plane import ControlPlane, Registry
from .control_plane.server import run_server


def main() -> None:
    ap = argparse.ArgumentParser(description="控制面 server（注册中心 + 路由 + 离线队列）")
    ap.add_argument("--config", default="config/boards.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    cp = cfg.control_plane
    token = os.getenv("AUTOTEST_CP_TOKEN") or cp.token
    plane = ControlPlane(registry=Registry(ttl=cp.ttl))
    print(f"控制面监听 {cp.host}:{cp.port}  ttl={cp.ttl}s  mcp=/mcp  注册=/gateways")
    run_server(plane, cp.host, cp.port, token)


if __name__ == "__main__":
    sys.exit(main())
