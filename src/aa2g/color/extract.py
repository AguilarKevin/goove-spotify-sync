"""Album-art → color palette.

Pulls an image URL, runs k-means in RGB space, scores each cluster in HSV
for the different "strategies" (vibrant / muted / dark-vibrant / dominant).
"""

from __future__ import annotations

import argparse
import colorsys
import io
import logging
import sys
from dataclasses import dataclass
from functools import lru_cache

import httpx
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

log = logging.getLogger(__name__)

THUMB_SIZE = 100
N_CLUSTERS = 5

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    """Four ranked color options. Each is an (R, G, B) tuple in 0–255."""
    dominant: RGB
    vibrant: RGB
    muted: RGB
    dark_vibrant: RGB

    def pick(self, strategy: str) -> RGB:
        return getattr(self, strategy.replace("-", "_"))


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)


def _score_cluster(rgb: np.ndarray, weight: float, strategy: str) -> float:
    _, s, v = _rgb_to_hsv(rgb)
    if strategy == "vibrant":
        return s * v * weight
    if strategy == "muted":
        return (1 - s) * weight if s < 0.5 else 0.0
    if strategy == "dark_vibrant":
        return s * (1 - v) * weight
    if strategy == "dominant":
        return float(weight)
    raise ValueError(f"unknown strategy: {strategy}")


def palette_from_image(img: Image.Image) -> Palette:
    img = img.convert("RGB").resize((THUMB_SIZE, THUMB_SIZE), Image.Resampling.BILINEAR)
    pixels = np.asarray(img).reshape(-1, 3).astype(np.float32)
    km = KMeans(n_clusters=N_CLUSTERS, n_init=4, random_state=0).fit(pixels)
    centers = km.cluster_centers_
    weights = np.bincount(km.labels_, minlength=N_CLUSTERS) / len(km.labels_)

    def best_for(strategy: str) -> RGB:
        scores = [_score_cluster(centers[i], weights[i], strategy) for i in range(N_CLUSTERS)]
        idx = int(np.argmax(scores))
        if scores[idx] <= 0:
            # No cluster matched the strategy (e.g. all saturated for "muted").
            # Fall back to the largest cluster.
            idx = int(np.argmax(weights))
        c = centers[idx]
        return (int(c[0]), int(c[1]), int(c[2]))

    return Palette(
        dominant=best_for("dominant"),
        vibrant=best_for("vibrant"),
        muted=best_for("muted"),
        dark_vibrant=best_for("dark_vibrant"),
    )


@lru_cache(maxsize=32)
def palette_from_url(url: str) -> Palette:
    with httpx.Client(timeout=10) as client:
        resp = client.get(url)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    return palette_from_image(img)


def _ansi_block(rgb: RGB) -> str:
    r, g, b = rgb
    return f"\x1b[48;2;{r};{g};{b}m    \x1b[0m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aa2g.color.extract")
    parser.add_argument("url", help="URL of album art image")
    args = parser.parse_args(argv)
    pal = palette_from_url(args.url)
    for name in ("dominant", "vibrant", "muted", "dark_vibrant"):
        rgb = pal.pick(name)
        print(f"  {_ansi_block(rgb)} {name:<14} rgb{rgb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
