from autotest_mcp.tools.hardware import HardwareController, MockRelayBackend


def test_press_button_timing():
    sleeps = []
    backend = MockRelayBackend()
    hw = HardwareController(backend, sleep=sleeps.append)
    res = hw.press_button(2, duration_ms=150)
    assert res == {"action": "press", "relay": 2, "duration_ms": 150}
    # 闭合 -> 延时 0.15 -> 断开
    assert backend.actions == [(2, True), (2, False)]
    assert sleeps == [0.15]


def test_power_cycle_timing():
    sleeps = []
    backend = MockRelayBackend()
    hw = HardwareController(backend, sleep=sleeps.append)
    hw.power_cycle(0, off_delay_s=2.0)
    assert backend.actions == [(0, False), (0, True)]
    assert sleeps == [2.0]
