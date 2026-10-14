"""按明确文件清单构建麦麦寻玩技能包。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SLUG = "maimai-toy-finder"
VERSION = "0.1.1"
TOP_FILES = ("SKILL.md", "README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md",
             "mcp-config.example.json", "LICENSE", ".gitignore", ".gitattributes")
FOLDERS = {"scripts": {".py"}, "references": {".json", ".md"}, "agents": {".yaml"},
           "tests": {".py"}, "docs": {".md"}, "examples": {".json", ".md"}}


def release_files() -> list[Path]:
    files = [ROOT / name for name in TOP_FILES]
    for folder, suffixes in FOLDERS.items():
        files.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts)
    token = os.environ.get("MCD_MCP_TOKEN", "").encode()
    for path in files:
        if not path.is_file() or path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError("发布文件缺失或超出项目目录：" + str(path.relative_to(ROOT)))
        if token and token in path.read_bytes():
            raise ValueError("检测到真实令牌，已停止打包：" + str(path.relative_to(ROOT)))
    return sorted(files)


def main() -> None:
    files = release_files()
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / f"{SLUG}-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in files:
            output.write(path, str(Path(SLUG) / path.relative_to(ROOT)))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".sha256").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    print(f"麦麦寻玩技能包已生成：{archive}，共 {len(files)} 个文件。")
    print("SHA-256：" + digest)


if __name__ == "__main__":
    main()
