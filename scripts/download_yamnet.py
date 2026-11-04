#!/usr/bin/env python3
"""Download the YAMNet SavedModel for C3 and cache it locally.

Run at image build time (see services/c3_data/Dockerfile) so the container starts
offline. Downloads YAMNet via TensorFlow Hub and copies it, together with its
521-class map CSV, into a target directory laid out as ``<target>/yamnet/1``.

Usage:
    python scripts/download_yamnet.py --target /models
    # -> /models/yamnet/1/            (SavedModel)
    #    /models/yamnet/1/yamnet_class_map.csv

The runtime loads it with ``tensorflow_hub.load("/models/yamnet/1")`` and reads
class names from ``model.class_map_path()``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# TF Hub handle for the YAMNet SavedModel (TF2).
YAMNET_HANDLE = "https://tfhub.dev/google/yamnet/1"


def download(target: Path) -> Path:
    import tensorflow_hub as hub

    dest = target / "yamnet" / "1"
    dest.mkdir(parents=True, exist_ok=True)

    print(f"[download_yamnet] loading {YAMNET_HANDLE} via tensorflow_hub ...", flush=True)
    model = hub.load(YAMNET_HANDLE)

    # hub.load caches the SavedModel under TFHUB_CACHE_DIR; resolve its path and
    # copy the resolved model into <target>/yamnet/1 so the image is self-contained.
    resolved = Path(hub.resolve(YAMNET_HANDLE))
    print(f"[download_yamnet] resolved cache dir: {resolved}", flush=True)
    if resolved.resolve() != dest.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(resolved, dest)

    # Copy the class map CSV next to the model for easy access by the runner.
    class_map_src = Path(model.class_map_path().numpy().decode("utf-8"))
    class_map_dst = dest / "yamnet_class_map.csv"
    if class_map_src.exists() and class_map_src.resolve() != class_map_dst.resolve():
        shutil.copyfile(class_map_src, class_map_dst)
    print(f"[download_yamnet] class map: {class_map_dst}", flush=True)

    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download YAMNet SavedModel for C3.")
    parser.add_argument(
        "--target",
        default="/models",
        help="Directory to place the model into (as <target>/yamnet/1). Default: /models",
    )
    args = parser.parse_args(argv)

    dest = download(Path(args.target))
    saved_model = dest / "saved_model.pb"
    if not saved_model.exists():
        print(f"[download_yamnet] ERROR: {saved_model} missing after download", file=sys.stderr)
        return 1
    print(f"[download_yamnet] done: {dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
