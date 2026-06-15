from autotest_mcp.tools import flasher

from conftest import make_run_stub


def test_flash_combined_bin(tmp_path):
    binf = tmp_path / "app.bin"
    binf.write_bytes(b"firmware")
    rec = []
    res = flasher.flash("COM5", 921600, str(binf), run=make_run_stub(returncode=0, record=rec))
    assert res["ok"] is True
    cmd = rec[0]
    assert cmd[-2:] == ["0x0", str(binf)]
    assert "write_flash" in cmd and "--port" in cmd and "COM5" in cmd


def test_flash_from_build_dir(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "flash_args").write_text("--flash_mode dio\n0x10000 app.bin\n")
    rec = []
    res = flasher.flash("COM5", 921600, str(build), run=make_run_stub(returncode=0, record=rec))
    assert res["ok"] is True
    assert rec[0][-1].startswith("@") and "flash_args" in rec[0][-1]


def test_flash_invalid_target(tmp_path):
    res = flasher.flash("COM5", 921600, str(tmp_path / "nope"), run=make_run_stub())
    assert res["ok"] is False
    assert "flash_args" in res["error"]
