from autotest_mcp.config import BoardConfig
from autotest_mcp.tools.device import DeviceManager


def _cfg(port="COM5"):
    return BoardConfig(port=port, baud=115200, power_relay=0)


def test_probe_online():
    class Ser:
        def close(self): ...
    dm = DeviceManager({"b": _cfg()}, open_serial=lambda *a, **k: Ser())
    assert dm.probe("COM5") is True


def test_probe_offline():
    def boom(*a, **k):
        raise OSError("no such device")
    dm = DeviceManager({"b": _cfg()}, open_serial=boom)
    assert dm.probe("COM5") is False


def test_list_and_get():
    dm = DeviceManager({"b": _cfg("COM7")}, open_serial=lambda *a, **k: type("S", (), {"close": lambda self: None})())
    boards = dm.list_boards()
    assert boards[0]["id"] == "b" and boards[0]["port"] == "COM7"
    assert dm.get("b").port == "COM7"


def test_get_unknown_raises():
    dm = DeviceManager({}, open_serial=lambda *a, **k: None)
    try:
        dm.get("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")
