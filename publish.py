"""Publish source and a complete offline installer using Git Credential Manager.

No credentials are written to disk. Interrupted draft uploads can be retried.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = "hansy1026/comfyui-imagen-app"
API = "https://api.github.com"
SOURCE = [".gitignore", "AGENTS.md", "README.md", "CHANGELOG.md", "app.py",
          "workflows.py", "requirements.txt", "requirements-build.txt", "assets",
          "licenses", "installer.iss", "生图app.spec", "安装说明.txt",
          "publish.py", "build-release.ps1", "test_publish.py"]


def git(*args, capture=False):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, text=True,
                          encoding="utf-8", capture_output=capture).stdout


def credentials():
    result = subprocess.run(
        ["git", "-c", "credential.interactive=false", "credential", "fill"],
        input="protocol=https\nhost=github.com\nusername=hansy1026\n\n",
        text=True, capture_output=True, check=True)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not fields.get("password"):
        raise RuntimeError("GitHub credentials unavailable. Sign in through Git Credential Manager.")
    return fields["password"]


class GitHub:
    def __init__(self):
        self.token = credentials()

    def request(self, path, method="GET", payload=None, stream=None, size=None):
        url = path if path.startswith("https://") else API + path
        if urllib.parse.urlparse(url).hostname not in {"api.github.com", "uploads.github.com"}:
            raise ValueError("Unexpected GitHub host")
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json", "User-Agent": "StarCanvas-Publisher"}
        data = json.dumps(payload).encode() if payload is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        if stream is not None:
            data = stream
            headers.update({"Content-Type": "application/octet-stream", "Content-Length": str(size)})
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=300) as response:
            body = response.read()
            return json.loads(body) if body else None


def installer_files(folder, version):
    prefix = f"StarCanvas-Offline-Setup-{version}"
    exe = folder / (prefix + ".exe")
    bins = sorted(folder.glob(prefix + "-*.bin"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    if not exe.is_file() or not bins:
        raise ValueError("Complete installer EXE and BIN volumes are required")
    if [int(p.stem.rsplit("-", 1)[1]) for p in bins] != list(range(1, len(bins) + 1)):
        raise ValueError("Missing installer volume")
    files = [exe, *bins, folder / "安装说明.txt"]
    for path in files:
        if not path.is_file() or not 0 < path.stat().st_size < 2 ** 31:
            raise ValueError(f"Missing/empty/oversized release asset: {path.name}")
    return files


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def matches(asset, path, digest):
    return (asset.get("state") == "uploaded" and asset.get("size") == path.stat().st_size
            and asset.get("digest") == "sha256:" + digest)


class Progress:
    def __init__(self, file, name, size):
        self.file, self.name, self.size = file, name, size
        self.sent, self.last = 0, time.monotonic()

    def read(self, amount=-1):
        chunk = self.file.read(amount)
        self.sent += len(chunk)
        if time.monotonic() - self.last > 25:
            print(f"{self.name}: {self.sent / self.size:.1%}", flush=True)
            self.last = time.monotonic()
        return chunk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-dir", type=Path, default=Path("D:/生图app/离线安装包"))
    parser.add_argument("--create-public-repository", action="store_true")
    args = parser.parse_args()
    content = (ROOT / "installer.iss").read_text(encoding="utf-8-sig")
    version = re.search(r"^AppVersion=(\d+\.\d+\.\d+)$", content, re.M)[1]
    files = installer_files(args.installer_dir.resolve(), version)
    api = GitHub()
    if api.request("/user")["login"].lower() != "hansy1026":
        raise RuntimeError("Wrong GitHub account")
    try:
        repo = api.request("/repos/" + REPO)
    except urllib.error.HTTPError as error:
        if error.code != 404 or not args.create_public_repository:
            raise
        repo = api.request("/user/repos", "POST", {
            "name": REPO.split("/")[1], "private": False,
            "description": "星绘工坊：支持六种 ComfyUI 工作流的 Windows 离线生图应用",
            "auto_init": False})
    if not (ROOT / ".git").exists():
        git("init", "-b", "main")
        git("remote", "add", "origin", repo["clone_url"])
    if git("remote", "get-url", "origin", capture=True).strip() != repo["clone_url"]:
        raise RuntimeError("Unexpected Git origin; refusing to publish")
    git("add", "--", *SOURCE)
    staged = git("diff", "--cached", "--name-only", "-z", capture=True).rstrip("\0").split("\0")
    staged = [name for name in staged if name]
    for name in staged:
        if not any(name == entry or name.startswith(entry + "/") for entry in SOURCE):
            raise RuntimeError(f"Unexpected staged file: {name}")
    if staged:
        git("commit", "-m", f"Publish StarCanvas {version}")
    git("push", "-u", "origin", "HEAD:main")
    commit = git("rev-parse", "HEAD", capture=True).strip()
    tag = "v" + version
    releases = api.request(f"/repos/{REPO}/releases?per_page=100")
    release = next((item for item in releases if item["tag_name"] == tag), None)
    body = (f"## 星绘工坊 {version} · Windows 完全离线安装版\n\n"
            "下载 EXE 和全部同名前缀的 BIN 分卷，放在同一文件夹后运行 EXE。"
            "不要选择 Source code 代替安装包。\n\n"
            "需要 Windows 10/11 64 位、NVIDIA 显卡 6 GB 起；建议 32 GB 内存。"
            "完整包约 31 GiB。详见 install-guide.txt。\n\n"
            "Qwen 工作流仅限非商业研究/评估；Krea 按其社区许可和使用政策使用。"
            "请先阅读仓库 licenses 目录。\n\n" + (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    if release is None:
        release = api.request(f"/repos/{REPO}/releases", "POST", {
            "tag_name": tag, "target_commitish": commit, "name": f"星绘工坊 {version}",
            "body": body, "draft": True})
    else:
        # Published versions are immutable in this workflow; increment version for changed code.
        try:
            tagged = api.request(f"/repos/{REPO}/commits/{tag}")["sha"]
        except urllib.error.HTTPError as error:
            if error.code != 404 or not release["draft"]:
                raise
            tagged = release["target_commitish"]
        if tagged != commit:
            raise RuntimeError("Version already belongs to another commit; increment AppVersion")
    print(f"Source: {repo['html_url']} | Release {tag} draft={release['draft']}", flush=True)
    entries = []
    for path in files:
        print("Hashing " + path.name, flush=True)
        entries.append((path, "install-guide.txt" if path.suffix == ".txt" else path.name, sha256(path)))
    manifest = ROOT / ".git" / "SHA256SUMS.txt"
    manifest.write_text("".join(f"{digest}  {name}\n" for _, name, digest in entries), encoding="utf-8")
    entries.append((manifest, manifest.name, sha256(manifest)))
    for path, name, digest in entries:
        for attempt in range(3):
            assets = api.request(f"/repos/{REPO}/releases/{release['id']}/assets?per_page=100")
            existing = next((asset for asset in assets if asset["name"] == name), None)
            if existing and matches(existing, path, digest):
                print("Verified " + name, flush=True)
                break
            if not release["draft"]:
                raise RuntimeError("Published release differs from local files; use a new version")
            if existing:
                api.request(f"/repos/{REPO}/releases/assets/{existing['id']}", "DELETE")
            try:
                upload = release["upload_url"].split("{")[0] + "?name=" + urllib.parse.quote(name)
                print(f"Uploading {name} ({path.stat().st_size:,} bytes), attempt {attempt+1}", flush=True)
                with path.open("rb") as file:
                    asset = api.request(upload, "POST", stream=Progress(file, name, path.stat().st_size),
                                        size=path.stat().st_size)
                if not matches(asset, path, digest):
                    raise RuntimeError("Uploaded asset digest does not match: " + name)
                print("Verified " + name, flush=True)
                break
            except (OSError, RuntimeError) as error:
                if attempt == 2:
                    raise
                print(f"Upload interrupted ({type(error).__name__}); retrying", flush=True)
                time.sleep(3)
    # Only expose the download after every expected asset has a matching server-side SHA256.
    assets = api.request(f"/repos/{REPO}/releases/{release['id']}/assets?per_page=100")
    by_name = {asset["name"]: asset for asset in assets}
    if not all(matches(by_name.get(name, {}), path, digest) for path, name, digest in entries):
        raise RuntimeError("Final release verification failed")
    if release["draft"]:
        release = api.request(f"/repos/{REPO}/releases/{release['id']}", "PATCH", {"draft": False})
    print("Published " + release["html_url"], flush=True)
    folder = args.installer_dir.resolve()
    for old in folder.iterdir():
        found = re.fullmatch(r"StarCanvas-Offline-Setup-(\d+\.\d+\.\d+)(?:-\d+)?\.(?:exe|bin)", old.name)
        if found and found[1] != version and old.is_file() and old.resolve().parent == folder:
            old.unlink()
            print("Removed old local installer: " + old.name, flush=True)


if __name__ == "__main__":
    main()
