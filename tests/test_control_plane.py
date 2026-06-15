"""控制面测试：注册/心跳/TTL、路由在线网关、离线入队、上线 drain、registrar、server 工具冒烟。"""
import asyncio
import json

import pytest

from autotest_mcp.control_plane import ControlPlane, Registry
from autotest_mcp.control_plane.registrar import GatewayRegistrar
from autotest_mcp.control_plane.server import build_control_plane
from autotest_mcp.mcp_client import FakeHardwareClient


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _structured(call_result):
    if isinstance(call_result, tuple) and len(call_result) == 2:
        _content, structured = call_result
        # 仅当结构是 {'result': <tool输出>}（list_gateways 这类返回 list 时）才解包；
        # call_hardware 这类返回 dict 时 structured 就是输出本身（即便它含 'result' 键）。
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    first = call_result[0] if isinstance(call_result, list) else call_result
    text = getattr(first, "text", None)
    return json.loads(text) if text else call_result


# ---------- Registry ----------

def test_registry_online_ttl_and_board_lookup():
    clk = FakeClock()
    reg = Registry(ttl=10.0, clock=clk)
    reg.register("gw1", "http://gw1", "t", ["boardA"])
    assert reg.gateway_for_board("boardA") is not None  # 在线
    clk.t = 11.0  # 超过 TTL → 离线
    assert reg.gateway_for_board("boardA") is None
    reg.heartbeat("gw1")  # 心跳续命
    assert reg.gateway_for_board("boardA") is not None


def test_registry_picks_most_recent_gateway():
    clk = FakeClock()
    reg = Registry(ttl=100.0, clock=clk)
    reg.register("gw1", "u1", "", ["boardA"])
    clk.t = 5.0
    reg.register("gw2", "u2", "", ["boardA"])  # 更晚注册 → last_seen 更大
    assert reg.gateway_for_board("boardA").id == "gw2"


# ---------- ControlPlane routing ----------

@pytest.mark.asyncio
async def test_route_to_online_gateway():
    plane = ControlPlane(make_client=lambda gw: FakeHardwareClient("boardA", panic=False))
    plane.register_gateway("gw1", "http://gw", "t", ["boardA"])
    res = await plane.call_hardware("boardA", "capture_serial", {"board_id": "boardA", "duration_s": 1})
    assert res["queued"] is False
    assert res["gateway_id"] == "gw1"
    assert res["result"]["panic_detected"] is False


@pytest.mark.asyncio
async def test_queue_when_no_gateway():
    plane = ControlPlane(make_client=lambda gw: FakeHardwareClient())
    res = await plane.call_hardware("boardA", "flash", {"board_id": "boardA", "bin_or_build_dir": "x"})
    assert res["queued"] is True
    assert plane.queue.pending("boardA")


@pytest.mark.asyncio
async def test_unknown_op_rejected():
    plane = ControlPlane(make_client=lambda gw: FakeHardwareClient())
    res = await plane.call_hardware("boardA", "symbolize", {"text": "x"})
    assert res["ok"] is False and "unknown" in res["error"]


@pytest.mark.asyncio
async def test_drain_runs_queued_jobs_on_online():
    plane = ControlPlane(make_client=lambda gw: FakeHardwareClient("boardA", panic=False))
    # 离线时入队
    await plane.call_hardware("boardA", "capture_serial", {"board_id": "boardA", "duration_s": 1})
    assert plane.queue.pending("boardA")
    # 网关上线 → drain
    plane.register_gateway("gw1", "http://gw", "t", ["boardA"])
    done = await plane.drain_pending("gw1")
    assert done and done[0].status == "done"
    assert plane.queue.pending("boardA") == []


@pytest.mark.asyncio
async def test_drain_skips_offline_gateway():
    clk = FakeClock()
    plane = ControlPlane(registry=Registry(ttl=1.0, clock=clk), make_client=lambda gw: FakeHardwareClient())
    plane.register_gateway("gw1", "http://gw", "t", ["boardA"])
    await plane.call_hardware("boardA", "flash", {"board_id": "boardA", "bin_or_build_dir": "x"})  # 路由成功(在线)
    # 不再排队；这里验证 drain 对离线网关不做事
    clk.t = 5.0
    assert await plane.drain_pending("gw1") == []


# ---------- Registrar ----------

@pytest.mark.asyncio
async def test_registrar_register_and_heartbeat():
    calls = []

    async def fake_post(url, payload, headers):
        calls.append((url, payload, headers))
        return {"ok": True}

    reg = GatewayRegistrar(
        "http://cp:8788", "gw1", "http://gw:8787", "gt", ["boardA"],
        cp_token="cptok", interval=0.01, post=fake_post,
    )
    await reg.register()
    await reg.heartbeat()
    assert calls[0][0].endswith("/gateways/gw1/register")
    assert calls[0][1]["boards"] == ["boardA"]
    assert calls[0][2]["Authorization"] == "Bearer cptok"
    assert calls[1][0].endswith("/gateways/gw1/heartbeat")


@pytest.mark.asyncio
async def test_registrar_background_loop_heartbeats():
    calls = []

    async def fake_post(url, payload, headers):
        calls.append(url)
        return {"ok": True}

    reg = GatewayRegistrar("http://cp", "gw1", "u", "t", ["boardA"], interval=0.01, post=fake_post)
    await reg.start()
    await asyncio.sleep(0.05)
    await reg.stop()
    # 至少一次 register + 多次 heartbeat
    assert any("register" in c for c in calls)
    assert sum("heartbeat" in c for c in calls) >= 1


# ---------- Server tools smoke ----------

@pytest.mark.asyncio
async def test_server_tools_end_to_end():
    plane = ControlPlane(make_client=lambda gw: FakeHardwareClient("boardA", panic=False))
    mcp = build_control_plane(plane)
    await mcp.call_tool("register_gateway", {"gw_id": "gw1", "url": "http://gw", "token": "", "boards": ["boardA"]})
    gws = _structured(await mcp.call_tool("list_gateways", {}))
    assert len(gws) == 1 and gws[0]["online"] is True
    res = _structured(await mcp.call_tool("call_hardware", {"board": "boardA", "op": "capture_serial", "args": {"board_id": "boardA", "duration_s": 1}}))
    assert res["queued"] is False and res["gateway_id"] == "gw1"
