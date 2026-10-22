#!/usr/bin/env python3
"""Phase-1 probing MVP for the model-monitor agent.

Given a servable open-weight model and a labelled, *non-hazardous* safety
dataset, this script:

  1. loads the model once with a single batched hooked forward pass
     (HF ``output_hidden_states=True`` -- NOT a serving engine; vLLM/SGLang do
     not expose the residual stream),
  2. extracts the residual-stream activation at one chosen layer, pooled over
     tokens (last-token by default), caches it to disk under the project share,
  3. trains + evaluates a linear probe (logistic regression) with a held-out
     split and reports AUROC / accuracy / TPR@FPR with a bootstrap CI,
  4. writes a structured JSON result in a shape close to the
     ``neurico-safety-result`` schema used by the safety-evals skill.

WHY A HOOKED FORWARD, NOT vLLM: generation engines batch and page KV-cache for
throughput and deliberately hide internals. Activation extraction needs the
hidden states, so we run a plain batched forward in ``torch.inference_mode()``
with bf16 + FlashAttention/SDPA. Use vLLM/SGLang only for the generation-heavy
*monitoring* lane (sampling many completions to judge), never for probing.

This is a SCAFFOLD: model/data paths are stubs, and the data loader has a
``TODO`` where the real dataset adapter goes. It is written to be import-correct
against current library APIs (transformers >= 4.44, torch >= 2.3,
scikit-learn >= 1.3); it is not meant to be executed on a login node -- launch
it on a GPU via the dsi-slurm skill.

Example (run on a compute node, inside the mech-interp uv venv):
    python probe_mvp.py \
        --model google/gemma-2-2b-it \
        --data  $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl \
        --layer 12 --pool last \
        --out   results/mech-interp/xstest__gemma-2-2b-it__L12.json

Hygiene (see the mech-interp SKILL.md):
  * HF cache stays on the share: export HF_HOME=$NEURICO_HF_CACHE
    (/net/spaces/chenhao/chai-lab-models/haokunliu/models/hf_cache).
  * Activation dumps go under the share (--cache-dir), NEVER under /home.
  * Use the GPU(s) in CUDA_VISIBLE_DEVICES only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# --------------------------------------------------------------------------------------
# Paths / hygiene: everything heavy lives on the project share, never under /home.
# --------------------------------------------------------------------------------------
PROJECT_SHARE = Path(
    os.environ.get("NEURICO_MODELS_DIR", "/net/spaces/chenhao/chai-lab-models/haokunliu/models")
)
DEFAULT_HF_CACHE = os.environ.get(
    "NEURICO_HF_CACHE", str(PROJECT_SHARE / "hf_cache")
)
DEFAULT_ACT_CACHE = os.environ.get(
    "NEURICO_MECH_INTERP_CACHE", str(PROJECT_SHARE / "mech_interp" / "activations")
)


@dataclass
class ProbeConfig:
    model: str = "google/gemma-2-2b-it"   # Phase-1 default: small, fast, Gemma-Scope SAEs exist
    data: str = ""                         # JSONL with {"text": str, "label": 0|1}
    layer: int = 12                        # residual-stream layer index (hidden_states[layer])
    pool: str = "last"                     # last | mean
    max_length: int = 512
    batch_size: int = 16
    test_size: float = 0.3
    seed: int = 0
    dtype: str = "bfloat16"
    attn_impl: str = "sdpa"                # "flash_attention_2" if flash-attn is installed
    cache_dir: str = DEFAULT_ACT_CACHE
    out: str = "results/mech-interp/probe_result.json"


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
def load_labelled_jsonl(path: str) -> Tuple[List[str], np.ndarray]:
    """Load a labelled dataset of {"text": str, "label": 0|1} rows.

    TODO(phase-1): replace / extend with the real dataset adapter. Candidates:
      * XSTest (safe=0 vs unsafe=1): ~450 non-hazardous prompts. Primary choice;
        already in the safety KB catalog as ``xstest-safe``.
      * ToxicChat (lmsys/toxic-chat): larger toxic-vs-benign user prompts.
      * refusal-direction pair: AdvBench ``harmful_behaviors`` (label 1) vs an
        Alpaca ``harmless`` sample (label 0).
    Materialise whichever you pick to JSONL under
    ``$NEURICO_MODELS_DIR/datasets/<name>/`` so it is cached on the share and
    this loader stays dataset-agnostic.
    """
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


# --------------------------------------------------------------------------------------
# Activation extraction: one batched hooked forward pass (the efficient path).
# --------------------------------------------------------------------------------------
def extract_residual_activations(cfg: ProbeConfig, texts: List[str]) -> np.ndarray:
    """Return an (N, d_model) matrix of pooled layer-``cfg.layer`` residuals.

    Efficiency choices (justified):
      * one model load, batched forward, ``torch.inference_mode()`` (no autograd);
      * bf16 weights + FlashAttention-2/SDPA kernels;
      * ``output_hidden_states=True`` gives every layer's residual stream in one
        pass, so switching layers later costs nothing extra;
      * left-padding so the last real token is at index -1 for ``pool=last``.
    Results are cached to ``cfg.cache_dir`` keyed by (model, layer, pool, data).
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cache_key = f"{Path(cfg.model).name}__L{cfg.layer}__{cfg.pool}__{Path(cfg.data).stem}.npy"
    cache_path = Path(cfg.cache_dir) / cache_key
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        print(f"[cache] reusing activations: {cache_path}")
        return np.load(cache_path)

    dtype = getattr(torch, cfg.dtype)
    tok = AutoTokenizer.from_pretrained(cfg.model, cache_dir=DEFAULT_HF_CACHE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"  # keep the final real token at position -1

    model = AutoModelForCausalLM.from_pretrained(
        cfg.model,
        cache_dir=DEFAULT_HF_CACHE,
        torch_dtype=dtype,
        attn_implementation=cfg.attn_impl,
        device_map="auto",
    )
    model.eval()

    feats: List[np.ndarray] = []
    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, len(texts), cfg.batch_size):
            batch = texts[start : start + cfg.batch_size]
            enc = tok(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=cfg.max_length,
            ).to(model.device)
            out = model(**enc, output_hidden_states=True)
            # hidden_states: tuple(num_layers+1) of (B, T, d_model); [0] is the embedding.
            hs = out.hidden_states[cfg.layer]
            if cfg.pool == "last":
                pooled = hs[:, -1, :]  # left-padded => last real token
            elif cfg.pool == "mean":
                mask = enc["attention_mask"].unsqueeze(-1).to(hs.dtype)
                pooled = (hs * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            else:
                raise ValueError(f"unknown pool: {cfg.pool}")
            feats.append(pooled.float().cpu().numpy())
            print(f"  [{start + len(batch)}/{len(texts)}] extracted", flush=True)

    X = np.concatenate(feats, axis=0)
    np.save(cache_path, X)
    print(f"[extract] {X.shape} activations in {time.time() - t0:.1f}s -> {cache_path}")
    return X


# --------------------------------------------------------------------------------------
# Probe: linear (logistic regression) with a held-out split and honest metrics.
# --------------------------------------------------------------------------------------
def tpr_at_fpr(y_true: np.ndarray, scores: np.ndarray, target_fpr: float = 0.05) -> float:
    from sklearn.metrics import roc_curve

    fpr, tpr, _ = roc_curve(y_true, scores)
    ok = fpr <= target_fpr
    return float(tpr[ok].max()) if ok.any() else 0.0


def train_eval_probe(cfg: ProbeConfig, X: np.ndarray, y: np.ndarray) -> Dict:
    """Train a linear probe. Pitfalls handled: a held-out split (no train/test
    leakage), standardisation fit on train only, class balancing, and a
    bootstrap CI on AUROC rather than a single point estimate."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=cfg.test_size, random_state=cfg.seed, stratify=y
    )
    clf = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0),
    )
    clf.fit(X_tr, y_tr)
    scores = clf.predict_proba(X_te)[:, 1]
    preds = (scores >= 0.5).astype(int)

    auroc = float(roc_auc_score(y_te, scores))
    acc = float(accuracy_score(y_te, preds))
    tpr05 = tpr_at_fpr(y_te, scores, 0.05)

    rng = np.random.default_rng(cfg.seed)
    boots = []
    for _ in range(1000):
        idx = rng.integers(0, len(y_te), len(y_te))
        if len(np.unique(y_te[idx])) < 2:
            continue
        boots.append(roc_auc_score(y_te[idx], scores[idx]))
    lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (None, None)

    return {
        "n_train": int(len(y_tr)),
        "n_test": int(len(y_te)),
        "d_model": int(X.shape[1]),
        "auroc": auroc,
        "auroc_ci95": [lo, hi],
        "accuracy": acc,
        "tpr_at_fpr05": tpr05,
        "pos_rate_test": float(y_te.mean()),
    }


def library_versions() -> Dict[str, Optional[str]]:
    versions: Dict[str, Optional[str]] = {}
    for mod in ("torch", "transformers", "sklearn", "numpy"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            versions[mod] = None
    return versions


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Phase-1 linear-probe MVP (model-monitor agent)")
    p.add_argument("--model", default=ProbeConfig.model)
    p.add_argument("--data", required=True, help="JSONL of {'text','label'} rows (non-hazardous)")
    p.add_argument("--layer", type=int, default=ProbeConfig.layer)
    p.add_argument("--pool", choices=["last", "mean"], default=ProbeConfig.pool)
    p.add_argument("--batch-size", type=int, default=ProbeConfig.batch_size)
    p.add_argument("--max-length", type=int, default=ProbeConfig.max_length)
    p.add_argument("--attn-impl", default=ProbeConfig.attn_impl)
    p.add_argument("--cache-dir", default=ProbeConfig.cache_dir)
    p.add_argument("--out", default=ProbeConfig.out)
    args = p.parse_args(argv)

    cfg = ProbeConfig(
        model=args.model, data=args.data, layer=args.layer, pool=args.pool,
        batch_size=args.batch_size, max_length=args.max_length,
        attn_impl=args.attn_impl, cache_dir=args.cache_dir, out=args.out,
    )

    texts, y = load_labelled_jsonl(cfg.data)
    print(f"[data] {len(texts)} rows, pos_rate={y.mean():.3f}")
    X = extract_residual_activations(cfg, texts)
    metrics = train_eval_probe(cfg, X, y)

    result = {
        "schema": "neurico-safety-result/v1",
        "eval_id": f"probe::{Path(cfg.data).stem}",
        "model_id": cfg.model,
        "n": int(len(texts)),
        "metrics": metrics,
        "probe": {"kind": "logreg", "layer": cfg.layer, "pool": cfg.pool, "site": "resid_post"},
        "task_args": asdict(cfg),
        "command": "python probe_mvp.py " + " ".join(sys.argv[1:]),
        "versions": library_versions(),
        "host": platform.node(),
        "status": "ok",
    }
    out_path = Path(cfg.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"[done] AUROC={metrics['auroc']:.3f} "
          f"CI95={metrics['auroc_ci95']} acc={metrics['accuracy']:.3f} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
