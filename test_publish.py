"""Run with python test_publish.py; no network or user files touched."""
from pathlib import Path
import tempfile
from publish import installer_files, matches, sha256

with tempfile.TemporaryDirectory() as temp:
    folder = Path(temp)
    prefix = "StarCanvas-Offline-Setup-1.2.3"
    for name in [prefix + ".exe", prefix + "-1.bin", prefix + "-3.bin", "安装说明.txt"]:
        (folder / name).write_bytes(b"test")
    try:
        installer_files(folder, "1.2.3")
        raise AssertionError("Missing volume was accepted")
    except ValueError:
        pass
    (folder / (prefix + "-2.bin")).write_bytes(b"test")
    files = installer_files(folder, "1.2.3")
    assert len(files) == 5
    digest = sha256(files[0])
    remote = {"state": "uploaded", "size": 4, "digest": "sha256:" + digest}
    assert matches(remote, files[0], digest)
    assert not matches(remote, files[0], "0" * 64)
    assert not matches({}, files[0], digest)
print("Publish checks passed: missing volume rejected; SHA256 verification enforced.")
