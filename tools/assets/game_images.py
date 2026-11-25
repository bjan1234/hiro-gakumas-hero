"""下载识别用的游戏原图到 resources/game_data：技能卡 skill_cards/、偶像卡 idol_cards/、P 饮料 drinks/，校验 SHA256。

usage: python tools/assets/game_images.py [--out resources/game_data]

原来由 KAA 的游戏数据更新器下载（kaa.game_data.updater）；去 KAA 后不再用 KAA 的代码，直接取它公开发布的数据包：
kotonebot/kaa-game-data 的 Release（每个版本对应一个 gakumasu-diff 提交，GPL-3.0），版本和 SHA256 钉死在下面，
换版本时改 TAG 和三个 SHA256。主数据（game.db）不从这里取，由 python -m hiro.state.master_db 从模拟器主数据生成。
已经是这个版本、三个目录都在就不重复下载。HIRO_KAA_GAME_DATA 指向别的目录时识别从那里读，这里的 --out 也要指过去。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "https://github.com/kotonebot/kaa-game-data/releases/download"
TAG = "data-edc305aac3ac0204806c96164ce36fb795ba81e1"
FILES = {  # 目录名（= 发布包名 <名>.zip，文件都在包的根上）→ SHA256
    "skill_cards": "ecfe06b81a7de1075f46a466455e4c2126e41bf30106754fad7ea76d728046b7",
    "idol_cards": "46d66cbe64198443573c251587221cc35615e54b5c4a724846cfd0c19212bca7",
    "drinks": "2e08b03544bd152c7e5a570067d31cd279159e17312dbe1aadb8f58aaa17bbb8",
}
VERSION_FILE = "images-version.txt"


def url(cat: str) -> str:
    return f"{REPO}/{TAG}/{cat}.zip"


def _current(out: Path) -> bool:
    v = out / VERSION_FILE
    return v.is_file() and v.read_text(encoding="utf-8").strip() == TAG and all((out / c).is_dir() for c in FILES)


def fetch(out: Path) -> list[str]:
    """把三类图下到 out/<类>/，返回这次下了哪些（按名字排序）；已是 TAG 版本返回空。

    先全部下完、校验通过再替换目录：任何一个校验不对就退出，已有的图不动。"""
    out = Path(out)
    if _current(out):
        return []
    blobs = {}
    for cat, sha in sorted(FILES.items()):
        print("下载", url(cat), flush=True)
        with urllib.request.urlopen(url(cat), timeout=600) as r:
            data = r.read()
        if (h := hashlib.sha256(data).hexdigest()) != sha:
            sys.exit(f"{cat}.zip 校验不对：{h}（应为 {sha}）")
        blobs[cat] = data
    out.mkdir(parents=True, exist_ok=True)
    for cat, data in blobs.items():
        tmp = out / f"{cat}.part"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                name = Path(info.filename).name  # 包里只有根上的图片；去掉路径防止解压到目录外
                if info.is_dir() or not name:
                    continue
                (tmp / name).write_bytes(z.read(info))
        shutil.rmtree(out / cat, ignore_errors=True)
        tmp.replace(out / cat)
    (out / VERSION_FILE).write_text(TAG + "\n", encoding="utf-8")
    return sorted(blobs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "resources" / "game_data"))
    args = ap.parse_args()
    got = fetch(Path(args.out))
    print("已下载：" + "、".join(got) if got else f"游戏图已是 {TAG}")


if __name__ == "__main__":
    main()
