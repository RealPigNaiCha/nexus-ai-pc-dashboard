from __future__ import annotations

import sys
from pathlib import Path

from fastembed import TextEmbedding


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: preload-model.py INSTALL_ROOT")
    install_root = Path(sys.argv[1]).resolve()
    cache_dir = install_root / "data" / "index" / "models" / "fastembed"
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(
        model_name="BAAI/bge-small-zh-v1.5",
        cache_dir=str(cache_dir),
        lazy_load=False,
    )
    vectors = list(model.embed(["Nexus AI-PC installation check"]))
    if len(vectors) != 1 or len(vectors[0]) != 512:
        raise RuntimeError("embedding model returned an unexpected vector shape")
    print("Embedding model is ready (512 dimensions).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
