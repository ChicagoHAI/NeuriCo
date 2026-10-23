#!/usr/bin/env python3
"""Shared helpers for the mech-interp MVP scripts.

Keeps model loading, residual-stream extraction and the (non-hazardous) XSTest
adapter in one place so ``probe_mvp.py``, ``sae_demo.py`` and ``causal_demo.py``
agree on the model, layer indexing and hygiene (HF cache on the share, bf16 +
SDPA, ``torch.inference_mode()``). Nothing here is model-family specific beyond
the standard ``model.model.layers[...]`` decoder stack shared by Gemma 2 / Llama
/ GPT-2-via-HF.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# --- hygiene: everything heavy on the project share, never /home -------------
PROJECT_SHARE = Path(
    os.environ.get("NEURICO_MODELS_DIR", "/net/spaces/chenhao/chai-lab-models/haokunliu/models")
)
HF_CACHE = os.environ.get("HF_HOME", os.environ.get("NEURICO_HF_CACHE", str(PROJECT_SHARE / "hf_cache")))
# Make sure every downstream HF call lands on the share.
os.environ.setdefault("HF_HOME", HF_CACHE)
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

DATASETS_DIR = PROJECT_SHARE / "datasets"


def _ensure_hf_token() -> None:
    """Best-effort: load HF_TOKEN by name from the NeuriCo .env for gated
    downloads (e.g. google/gemma-2-2b-it) when it is not already in the
    environment. The token is never printed. Override the path with
    NEURICO_ENV_FILE; set HF_TOKEN directly to skip this entirely."""
    if os.environ.get("HF_TOKEN"):
        return
    env_file = os.environ.get(
        "NEURICO_ENV_FILE",
        "/net/spaces/chenhao/chai-lab-models/haokunliu/safety/neurico/.env",
    )
    try:
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("HF_TOKEN="):
                    os.environ["HF_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except OSError:
        pass


_ensure_hf_token()


def resolve_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model_and_tokenizer(model_name: str, dtype: str = "bfloat16",
                             attn_impl: str = "sdpa"):
    """Load an HF causal LM in bf16 with a tokenizer configured for last-token
    pooling (left padding). Returns (model, tokenizer)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name, cache_dir=HF_CACHE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    torch_dtype = getattr(torch, dtype)
    kwargs = dict(cache_dir=HF_CACHE, torch_dtype=torch_dtype, attn_implementation=attn_impl)
    if torch.cuda.is_available():
        kwargs["device_map"] = "auto"
    model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs).eval()
    if not torch.cuda.is_available():
        model = model.to("cpu")
    return model, tok


def decoder_layers(model):
    """Return the list of transformer blocks for the common HF decoder stack."""
    # Gemma2/Llama/Mistral/Qwen: model.model.layers ; GPT-2: model.transformer.h
    if hasattr(model, "model") and hasattr(model.model, "layers"):
        return model.model.layers
    if hasattr(model, "transformer") and hasattr(model.transformer, "h"):
        return model.transformer.h
    raise AttributeError("could not locate decoder layer list on this model")


def extract_resid(model, tok, texts: List[str], layer: int, pool: str = "last",
                  batch_size: int = 16, max_length: int = 512) -> np.ndarray:
    """One batched hooked forward pass -> (N, d_model) pooled residual at
    ``hidden_states[layer]`` ([0] is the embedding layer)."""
    import torch

    feats: List[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            enc = tok(batch, return_tensors="pt", padding=True, truncation=True,
                      max_length=max_length).to(model.device)
            out = model(**enc, output_hidden_states=True)
            hs = out.hidden_states[layer]  # (B, T, d_model)
            if pool == "last":
                pooled = hs[:, -1, :]      # left-padded => last real token
            elif pool == "mean":
                mask = enc["attention_mask"].unsqueeze(-1).to(hs.dtype)
                pooled = (hs * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            else:
                raise ValueError(f"unknown pool: {pool}")
            feats.append(pooled.float().cpu().numpy())
    return np.concatenate(feats, axis=0)


# --- XSTest adapter (non-hazardous safe/unsafe proxy) ------------------------
# Canonical XSTest v2 prompts (CC-BY-4.0), served non-gated from the authors'
# GitHub. The HF mirror walledai/XSTest is gated, so we prefer the CSV.
XSTEST_CSV_URL = (
    "https://raw.githubusercontent.com/paul-rottger/exaggerated-safety/"
    "main/xstest_prompts.csv"
)


def materialize_xstest(out_path: Optional[str] = None) -> str:
    """Materialise XSTest to JSONL {"text","label"} on the share.
    label: unsafe(contrast)->1, safe->0. Returns the JSONL path. Idempotent.

    Source order: (1) the public CC-BY CSV on GitHub (non-gated); (2) the gated
    HF dataset walledai/XSTest as a fallback if the CSV is unreachable. In v2 the
    unsafe contrast prompts have a ``type`` starting with ``contrast``."""
    out = Path(out_path) if out_path else (DATASETS_DIR / "xstest" / "xstest.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return str(out)

    rows = []
    try:
        import csv
        import io
        import urllib.request

        with urllib.request.urlopen(XSTEST_CSV_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        for r in csv.DictReader(io.StringIO(text)):
            prompt = (r.get("prompt") or "").strip()
            if not prompt:
                continue
            lab = (r.get("label") or "").strip().lower()
            typ = (r.get("type") or "").strip().lower()
            # authoritative `label` column; fall back to the contrast-type convention
            label = 1 if (lab == "unsafe" or (not lab and typ.startswith("contrast"))) else 0
            rows.append((prompt, label))
        print(f"[xstest] fetched {len(rows)} rows from public CSV")
    except Exception as e:  # noqa: BLE001
        print(f"[xstest] CSV fetch failed ({type(e).__name__}: {e}); trying gated HF mirror")
        from datasets import load_dataset

        ds = load_dataset("walledai/XSTest", split="test", cache_dir=HF_CACHE)
        rows = [(str(r["prompt"]), 1 if str(r["label"]).strip().lower() == "unsafe" else 0)
                for r in ds]

    if not rows:
        raise RuntimeError("XSTest materialisation produced no rows")
    with open(out, "w", encoding="utf-8") as fh:
        for prompt, label in rows:
            fh.write(json.dumps({"text": prompt, "label": label}) + "\n")
    print(f"[xstest] wrote {len(rows)} rows -> {out}")
    return str(out)


def load_labelled_jsonl(path: str) -> Tuple[List[str], np.ndarray]:
    texts: List[str] = []
    labels: List[int] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            texts.append(str(row["text"]))
            labels.append(int(row["label"]))
    if not texts:
        raise ValueError(f"No rows loaded from {path}")
    return texts, np.asarray(labels, dtype=np.int64)
