from autotest_mcp.tools import serial_mon as sm

from conftest import FakeClock, FakeSerial


def test_capture_detects_panic_and_writes_log(tmp_path):
    chunks = [b"boot...\n", b"Guru Meditation Error: Core 0 panic\n", b"Backtrace: 0x40384000\n"]
    clk = FakeClock(step=0.4)
    res = sm.capture(
        "FAKE", 115200, duration_s=1.0, log_dir=str(tmp_path),
        open_serial=lambda *a, **k: FakeSerial(chunks),
        sleep=FakeClock.nosleep, monotonic=clk, board_id="boardA",
    )
    assert res["panic_detected"] is True
    assert res["lines"] >= 2
    log = (tmp_path / res["log_path"].split("/")[-1]).read_text(encoding="utf-8")
    assert "panic" in log


def test_capture_stops_on_pattern(tmp_path):
    chunks = [b"hello\n", b"READY\n", b"should not see\n"]
    clk = FakeClock(step=10.0)  # 即使时间已超，也应优先因 pattern 命中而停
    res = sm.capture(
        "FAKE", 115200, until_pattern="READY", log_dir=str(tmp_path),
        open_serial=lambda *a, **k: FakeSerial(chunks),
        sleep=FakeClock.nosleep, monotonic=clk, board_id="boardA",
    )
    assert res["matched_pattern"] == "READY"


def test_capture_injects_commands(tmp_path):
    ser_holder = {}

    def opener(*a, **k):
        s = FakeSerial([b"ok\n"])
        ser_holder["s"] = s
        return s

    sm.capture(
        "FAKE", 115200, duration_s=0.5, inject=["test> run", "test> status"],
        log_dir=str(tmp_path), open_serial=opener, sleep=FakeClock.nosleep,
        monotonic=FakeClock(step=1.0), board_id="boardA",
    )
    written = b"".join(ser_holder["s"].written)
    assert b"test> run" in written and b"test> status" in written
