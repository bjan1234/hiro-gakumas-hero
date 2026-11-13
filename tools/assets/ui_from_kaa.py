"""把 KAA 的界面模板搬进素材包 assets/pack/ui（去 KAA 第 1 / 3 步：判页和执行用自己的 hiro.vision.ui_templates）。

usage: python tools/assets/ui_from_kaa.py --kaa <KAA 仓库> InProduce.TextPItem InProduce.TextPDrinkMax ...

KAA 的模板定义在它生成的 kaa/tasks/R.py（TemplateMatchPrefab：template = ImageSlice(file_path=sprite_path("<id>.png"),
slice_rect=Rect(...) | None)、fixed、region），图在 kaa/sprites/<id>.png（已经是切好的模板）。名字沿用 R 的路径，
InPurodyuusu 写成 InProduce（KAA 的别名，ui_templates 里一直这么叫）。已有的条目不改，只加新的。
"""

import argparse
import ast
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "assets" / "pack" / "ui"
ALIAS = {"InPurodyuusu": "InProduce"}


def _rect(node) -> list[int] | None:
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Rect":
        kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        return [round(kw["x"]), round(kw["y"]), round(kw["w"]), round(kw["h"])]
    return None


def prefabs(r_py: Path) -> dict[str, dict]:
    """R.py → {"InProduce.TextPItem": {file_id, slice_rect, fixed, region}}。"""
    out: dict[str, dict] = {}

    def walk(cls: ast.ClassDef, path: list[str]) -> None:
        entry: dict = {}
        for st in cls.body:
            if isinstance(st, ast.ClassDef):
                walk(st, path + [st.name])
            elif isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                k, v = st.targets[0].id, st.value
                if k == "template" and isinstance(v, ast.Call):
                    kw = {a.arg: a.value for a in v.keywords}
                    fp = kw.get("file_path")
                    if isinstance(fp, ast.Call) and fp.args:
                        entry["file_id"] = ast.literal_eval(fp.args[0])
                    entry["slice_rect"] = _rect(kw.get("slice_rect"))
                elif k == "fixed":
                    entry["fixed"] = ast.literal_eval(v)
                elif k == "region":
                    entry["region"] = _rect(v)
        if "file_id" in entry:
            out[".".join([ALIAS.get(path[0], path[0]), *path[1:]])] = entry

    for node in ast.parse(r_py.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef):
            walk(node, [node.name])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kaa", required=True, help="KAA 仓库（有生成好的 kaa/tasks/R.py 和 kaa/sprites/）")
    ap.add_argument("names", nargs="+")
    args = ap.parse_args()
    kaa = Path(args.kaa)
    defs = prefabs(kaa / "kaa" / "tasks" / "R.py")
    cat_path = PACK / "templates.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    missing = [n for n in args.names if n not in defs]
    if missing:
        sys.exit(f"R.py 里没有：{missing}")
    for name in args.names:
        if name in cat["templates"]:
            print("已有", name)
            continue
        d = defs[name]
        shutil.copyfile(kaa / "kaa" / "sprites" / d["file_id"], PACK / f"{name}.png")
        e = {"file": f"{name}.png", "slice_rect": d["slice_rect"], "source": f"KAA {d['file_id']}"}
        if d.get("fixed"):
            e["fixed"] = True
        if d.get("region"):
            e["region"] = d["region"]
        cat["templates"][name] = e
        print("加", name, e)
    cat_path.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
