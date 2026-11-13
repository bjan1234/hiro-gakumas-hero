"""偶像卡图库（编成第 1 步选偶像）：和 KAA image_db 的 idols 库同一套做法，不依赖 KAA。

图：AssetSource.idol_dir()（KAA 公开数据的 idol_cards/，<skin id>_<n>.png）。描述子：HSV 三通道各 8 档的直方图，
画面均分 3×3 共 9 块分别算、各自 cv2.normalize 后拼接（同 KAA HistDescriptor(8)）；距离：卡方 0.5·Σ(a−b)²/(a+b)
（同 KAA 的 FlatIndex CHI2）。整库第一次用时现算（几百张，约 1 秒），之后缓存。
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import cv2
import numpy as np

BINS = 8


def descriptor(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    parts = []
    for i in range(3):
        for j in range(3):
            mask = np.zeros((h, w), np.uint8)
            mask[i * h // 3 : (i + 1) * h // 3, j * w // 3 : (j + 1) * w // 3] = 255
            hist = cv2.calcHist([hsv], [0, 1, 2], mask, [BINS] * 3, [0, 180, 0, 256, 0, 256])
            parts.append(cv2.normalize(hist, hist).flatten())
    return np.concatenate(parts).astype(np.float32)


def _idol_dir() -> Path | None:
    from hiro import plugins

    src = plugins.get("asset_source")
    return src.idol_dir() if src is not None and hasattr(src, "idol_dir") else None


@cache
def _db() -> tuple[tuple[str, ...], np.ndarray]:
    d = _idol_dir()
    files = sorted(d.glob("*.png")) if d is not None and d.is_dir() else []
    keys, vecs = [], []
    for f in files:
        img = cv2.imread(str(f))
        if img is not None:
            keys.append(f.name)
            vecs.append(descriptor(img))
    return tuple(keys), (np.stack(vecs) if vecs else np.zeros((0, BINS**3 * 9), np.float32))


def query(img: np.ndarray, threshold: float | None = None) -> tuple[str, float] | None:
    """最像的一张：(文件名, 卡方距离)；库是空的或距离 ≥ threshold 时 None。"""
    keys, mat = _db()
    if not keys:
        return None
    q = descriptor(img)
    d = 0.5 * np.sum((mat - q) ** 2 / (mat + q + 1e-10), axis=1)
    i = int(np.argmin(d))
    return None if threshold is not None and d[i] >= threshold else (keys[i], float(d[i]))
