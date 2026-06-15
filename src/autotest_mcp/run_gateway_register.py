"""网关注册 CLI：硬件网关（M0 server）启动后，向控制面注册 + 周期心跳。

  python -m autotest_mcp.run_gateway_register
  # 默认从 config 读 gateway_reg；家用 cp_url 填 tailscale，公司填内网
"""
from __future__ import annotations

import argparse
import asyncio

from .config import load_config
from .control_plane.registrar import GatewayRegistrar


def main() -> None:
    ap = argparse.ArgumentParser(description="硬件网关向控制面注册 + 心跳")
    ap.add_argument("--config", default="config/boards.yaml")
    ap.add_argument("--cp-url")
    ap.add_argument("--id")
    args = ap.parse_args()

    cfg = load_config(args.config)
    gr = cfg.gateway_reg
    reg = GatewayRegistrar(
        cp_url=args.cp_url or gr.cp_url,
        gw_id=args.id or gr.id,
        url=f"http://{cfg.server.host}:{cfg.server.port}/mcp",  # 本网关的 MCP 地址
        token=cfg.server.token,
        boards=gr.boards,
        cp_token=gr.cp_token,
        interval=gr.interval,
    )
    print(f"网关 {gr.id} → 注册到 {gr.cp_url}（boards={gr.boards}，interval={gr.interval}s）")
    asyncio.run(_run(reg))


async def _run(reg: GatewayRegistrar) -> None:
    await reg.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await reg.stop()


if __name__ == "__main__":
    main()
