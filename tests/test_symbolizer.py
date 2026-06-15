from autotest_mcp.tools import symbolizer as sym


def test_extract_addresses_prefers_backtrace_line():
    text = "some boot log\nBacktrace:0x40384000 0x40384abc 0x4038dead\nmore 0x0000fff text"
    addrs = sym.extract_addresses(text)
    # 只取 Backtrace 行里的地址，且去重
    assert addrs == ["0x40384000", "0x40384abc", "0x4038dead"]


def test_extract_addresses_fallback_all_hex():
    assert sym.extract_addresses("no backtrace here 0x40380001 0x40380002") == [
        "0x40380001",
        "0x40380002",
    ]


def test_symbolize_calls_addr2line(tmp_path):
    elf = tmp_path / "app.elf"
    elf.write_bytes(b"\x7fELF")
    a2l = tmp_path / "fake-addr2line"
    a2l.write_text("#!/bin/sh\necho stub\n")

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return sym.subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=cmd, returncode=0, stdout="app_main at foo.c:42\n", stderr=""
        )

    res = sym.symbolize(str(elf), "Backtrace: 0x40384000", addr2line=str(a2l), run=fake_run)
    assert res["addresses_found"] == 1
    assert res["symbolized"] == "app_main at foo.c:42"
    assert captured["cmd"][:4] == [str(a2l), "-pfiaC", "-e", str(elf)]


def test_symbolize_no_addresses():
    res = sym.symbolize("/anywhere.elf", "nothing useful here", addr2line="/x")
    assert res["addresses_found"] == 0
    assert "no addresses" in res["error"]


def test_symbolize_missing_addr2line(tmp_path):
    elf = tmp_path / "app.elf"
    elf.write_bytes(b"\x7fELF")
    res = sym.symbolize(str(elf), "Backtrace: 0x40384000", addr2line="/does/not/exist")
    assert "not found" in res["error"]
