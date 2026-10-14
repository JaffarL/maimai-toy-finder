"""将麦麦寻玩安装到本地技能目录。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

from build_release import ROOT, SLUG, release_files
from find_stores import ChineseParser


def install(skills_dir: Path) -> Path:
    target = skills_dir.expanduser().resolve() / SLUG
    if target.exists():
        raise ValueError(f"技能目录已存在：{target}。请先备份并移走旧目录，再重新安装。")
    files = release_files()
    target.mkdir(parents=True)
    for source in files:
        relative = source.relative_to(ROOT)
        # 保留技能运行及比赛说明；测试和发布证据留在源码包中。
        if relative.parts[0] == "tests":
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return target


def main() -> int:
    parser = ChineseParser(description="安装麦麦寻玩技能", add_help=False)
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示安装帮助并退出")
    default_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    parser.add_argument("--skills-dir", type=Path, default=default_home / "skills",
                        help="客户端的本地技能目录，默认为 Codex 技能目录")
    args = parser.parse_args()
    try:
        target = install(args.skills_dir)
    except (ValueError, OSError) as exc:
        print(f"安装未完成：{exc}")
        return 2
    print(f"麦麦寻玩已安装：{target}")
    print("在客户端开启新会话后，上传玩具图片并说出城市即可使用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
