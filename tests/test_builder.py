from autotest_mcp.tools import builder

from conftest import make_run_stub


def test_build_finds_artifacts(tmp_path):
    src = tmp_path / "fw"
    src.mkdir()
    build = src / "build"
    build.mkdir()
    (build / "myapp.bin").write_bytes(b"x")
    (build / "myapp.elf").write_bytes(b"\x7fELF")
    (build / "bootloader.bin").write_bytes(b"boot")
    (build / "flash_args").write_text("0x10000 myapp.bin\n")

    res = builder.build(str(src), idf_version="v5.3", backend="docker", run=make_run_stub(returncode=0))
    assert res["ok"] is True
    assert res["bin_path"].endswith("myapp.bin")  # 不误选 bootloader
    assert res["elf_path"].endswith("myapp.elf")
    assert res["flash_args_path"].endswith("flash_args")


def test_build_missing_source(tmp_path):
    res = builder.build(str(tmp_path / "nope"), run=make_run_stub())
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_build_local_uses_idf_py(tmp_path):
    src = tmp_path / "fw"
    src.mkdir()
    rec = []
    builder.build(str(src), backend="local", run=make_run_stub(returncode=0, record=rec))
    assert rec[0] == ["idf.py", "build"]
