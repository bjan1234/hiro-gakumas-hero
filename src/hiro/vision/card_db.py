"""卡面图库（选卡弹窗、相談货架、牌组卡格认卡）：和 KAA image_db 的 skill_cards_dialog 同一套做法，不依赖 KAA。

图：AssetSource.skill_card_dir()（KAA 公开数据 skill_cards/，按 IMREAD_COLOR 读，同 KAA）。描述子：OpenCV SIFT，nfeatures=500，
其余参数缺省（同 KAA SiftDescriptor(nfeatures=500)）。检索：所有卡的描述子放进 faiss 精确 L2 索引；KAA 用 IVFFlat、
nprobe = nlist = 100，等于全量搜索，所以结果相同。查询：截图每个描述子找 1 个最近邻，距离（L2 平方）≤ GOOD_MATCH_MAX_DIST
的给那张图投一票；按「票数多、其次最小距离小」排序（同 KAA ImageDatabase.query）。match：同一张卡的角色专属图（-hmsz 等后缀）
合并计票，最高 < MIN_VOTES 票不认（同 KAA match_card_region）。

描述子第一次用时现算（约两千张，几十秒），存到 cache/card_sift.npz，图库目录里的文件变了就重算。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

NFEATURES = 500
GOOD_MATCH_MAX_DIST = 20000.0
MIN_VOTES = 3
CACHE = Path(__file__).resolve().parents[3] / "cache" / "card_sift.npz"


@dataclass(frozen=True)
class Hit:
    key: str  # 图文件名去掉 .png（asset id）
    votes: int
    distance: float  # 最近的一次匹配距离（L2 平方）


def _card_dir() -> Path | None:
    from hiro import plugins

    src = plugins.get("asset_source")
    return src.skill_card_dir() if src is not None and hasattr(src, "skill_card_dir") else None


def _sift():
    return cv2.SIFT_create(nfeatures=NFEATURES)


def descriptors(img: np.ndarray) -> np.ndarray:
    _, d = _sift().detectAndCompute(img, None)
    return np.empty((0, 128), np.float32) if d is None else d.astype(np.float32)


def _signature(files: list[Path]) -> str:
    h = hashlib.sha1()
    for f in files:
        st = f.stat()
        h.update(f"{f.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


@cache
def _db() -> tuple[tuple[str, ...], np.ndarray, object]:
    """(keys, 每个描述子属于第几张图, faiss 索引)。"""
    import faiss

    d = _card_dir()
    files = sorted(d.glob("*.png")) if d is not None and d.is_dir() else []
    sig = _signature(files)
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=False)
        if str(z["sig"]) == sig:
            keys, owner, vecs = tuple(z["keys"].tolist()), z["owner"], z["vecs"]
        else:
            keys = ()
    else:
        keys = ()
    if not keys and files:
        logger.info("卡面图库：给 %d 张卡图算 SIFT 描述子（只算一次，存 %s）", len(files), CACHE)
        ks, owners, chunks = [], [], []
        for f in files:
            dsc = descriptors(cv2.imread(str(f), cv2.IMREAD_COLOR))
            if len(dsc):
                owners.append(np.full(len(dsc), len(ks), np.int32))
                chunks.append(dsc)
                ks.append(f.name.removesuffix(".png"))
        keys, owner, vecs = tuple(ks), np.concatenate(owners), np.concatenate(chunks)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(CACHE, sig=sig, keys=np.array(keys), owner=owner, vecs=vecs)
    if not keys:
        return (), np.zeros(0, np.int32), None
    index = faiss.IndexFlatL2(128)
    index.add(np.ascontiguousarray(vecs, dtype=np.float32))
    return keys, owner, index


def query(img: np.ndarray) -> list[Hit]:
    """全部有票的图，按票数降序、最小距离升序（同 KAA ImageDatabase.query 的局部描述子分支）。"""
    keys, owner, index = _db()
    q = descriptors(img)
    if index is None or not len(q):
        return []
    dist, lab = index.search(q, 1)
    votes: dict[int, int] = {}
    best: dict[int, float] = {}
    for dd, ll in zip(dist[:, 0], lab[:, 0]):
        if ll < 0 or float(dd) > GOOD_MATCH_MAX_DIST:
            continue
        k = int(owner[ll])
        votes[k] = votes.get(k, 0) + 1
        best[k] = min(best.get(k, float("inf")), float(dd))
    hits = [Hit(keys[k], v, best[k]) for k, v in votes.items()]
    return sorted(hits, key=lambda h: (-h.votes, h.distance))


def match(img: np.ndarray, *, min_votes: int = MIN_VOTES) -> str | None:
    """卡区截图 → base asset id（角色专属图合并计票，同 KAA match_card_region）；最高票 < min_votes 返回 None。"""
    from hiro.vision.deck import base_asset

    votes: dict[str, int] = {}
    best: dict[str, float] = {}
    for h in query(img):
        a = base_asset(h.key)
        votes[a] = votes.get(a, 0) + h.votes
        best[a] = min(best.get(a, float("inf")), h.distance)
    if not votes:
        return None
    top = min(votes, key=lambda a: (-votes[a], best[a]))
    return top if votes[top] >= min_votes else None
