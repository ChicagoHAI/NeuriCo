#!/usr/bin/env python3
"""Materialise the XSTest safe/unsafe proxy dataset to JSONL on the share.

XSTest (Röttger et al., 2023; walledai/XSTest) is 250 *safe* prompts that use
sensitive-sounding language plus 200 genuinely *unsafe* contrast prompts. It is
a non-hazardous proxy (no operational harmful content), which is exactly what
the mech-interp skill's rules require for probing/monitoring work.

    python prepare_xstest.py            # -> $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl
    python prepare_xstest.py --out /path/to/xstest.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mi_common as mi  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Materialise XSTest -> JSONL {text,label}")
    p.add_argument("--out", default=None, help="output JSONL path (default: share)")
    args = p.parse_args()
    path = mi.materialize_xstest(args.out)
    texts, y = mi.load_labelled_jsonl(path)
    print(f"[done] {len(texts)} rows, pos_rate(unsafe)={y.mean():.3f} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
