#!/usr/bin/env python3
"""Train and evaluate a linear probe on hidden activations.

    $NEURICO_SAFETY_VENV/bin/python probe.py --model Qwen/Qwen2.5-0.5B-Instruct \
        --data data/harmful_intent.jsonl --layer -1 --pool last --out results/safety/probe_harmful

Input: JSONL with {"text": ..., "label": 0|1} (optionally "split": train|dev|test; otherwise a
stratified 60/20/20 split with a fixed seed is made). Output directory gets:
  probe.npz           weights, bias, layer, pooling, normalisation stats
  metrics.json        held-out AUROC, accuracy, TPR at 1%/5% FPR with bootstrap 95% CIs, n per split
  result.json         the same in the neurico-safety-result/v1 schema (eval_id probe:<name>)
Never tune on the test split: C is chosen on dev.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_safety_package, workspace_root  # noqa: E402

add_safety_package()
from safety.kb import save_json, utc_now  # noqa: E402


def load_data(path: Path, seed: int) -> Dict[str, Tuple[List[str], np.ndarray]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("empty dataset")
    if all("split" in r for r in rows):
        splits = {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}
    else:
        rng = np.random.default_rng(seed)
        splits = {"train": [], "dev": [], "test": []}
        for label in sorted({int(r["label"]) for r in rows}):
            group = [r for r in rows if int(r["label"]) == label]
            rng.shuffle(group)
            n = len(group)
            splits["train"] += group[: int(0.6 * n)]
            splits["dev"] += group[int(0.6 * n): int(0.8 * n)]
            splits["test"] += group[int(0.8 * n):]
    return {s: ([r["text"] for r in rs], np.array([int(r["label"]) for r in rs])) for s, rs in splits.items()}


def extract(model_id: str, texts: List[str], layer: int, pool: str, batch_size: int, max_length: int,
            chat_template: bool) -> np.ndarray:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.padding_side = "right"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="auto")
    model.eval()
    feats = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start: start + batch_size]
        if chat_template and tokenizer.chat_template:
            batch = [tokenizer.apply_chat_template([{"role": "user", "content": t}], tokenize=False,
                                                   add_generation_prompt=True) for t in batch]
        enc = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=max_length)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.no_grad():
            out = model(**enc, output_hidden_states=True)
        hidden = out.hidden_states[layer].float()
        mask = enc["attention_mask"].unsqueeze(-1).float()
        if pool == "mean":
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
        else:
            last = enc["attention_mask"].sum(1) - 1
            pooled = hidden[torch.arange(hidden.shape[0]), last]
        feats.append(pooled.cpu().numpy())
        print(f"  extracted {min(start + batch_size, len(texts))}/{len(texts)}", flush=True)
    return np.concatenate(feats)


def tpr_at_fpr(y: np.ndarray, scores: np.ndarray, fpr_target: float) -> float:
    from sklearn.metrics import roc_curve
    fpr, tpr, _ = roc_curve(y, scores)
    ok = fpr <= fpr_target
    return float(tpr[ok].max()) if ok.any() else 0.0


def evaluate(y: np.ndarray, scores: np.ndarray, seed: int, n_boot: int = 1000) -> Dict[str, object]:
    from sklearn.metrics import accuracy_score, roc_auc_score
    rng = np.random.default_rng(seed)
    point = {"auroc": float(roc_auc_score(y, scores)), "accuracy": float(accuracy_score(y, scores > 0.5)),
             "tpr_at_1pct_fpr": tpr_at_fpr(y, scores, 0.01), "tpr_at_5pct_fpr": tpr_at_fpr(y, scores, 0.05)}
    boots: Dict[str, List[float]] = {k: [] for k in point}
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx].tolist())) < 2:
            continue
        boots["auroc"].append(roc_auc_score(y[idx], scores[idx]))
        boots["accuracy"].append(accuracy_score(y[idx], scores[idx] > 0.5))
        boots["tpr_at_1pct_fpr"].append(tpr_at_fpr(y[idx], scores[idx], 0.01))
        boots["tpr_at_5pct_fpr"].append(tpr_at_fpr(y[idx], scores[idx], 0.05))
    out: Dict[str, object] = {}
    for key, value in point.items():
        lo, hi = (np.percentile(boots[key], [2.5, 97.5]) if boots[key] else (value, value))
        out[key] = value
        out[f"{key}_ci95"] = [float(lo), float(hi)]
    out["n"] = int(len(y))
    out["n_positive"] = int(y.sum())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--layer", type=int, default=-1, help="hidden_states index (negative from the end)")
    parser.add_argument("--pool", choices=("last", "mean"), default="last")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--no-chat-template", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--name", default=None)
    parser.add_argument("--model-id", default=None, help="catalog model id for the result record")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from sklearn.linear_model import LogisticRegression

    root = workspace_root()
    name = args.name or f"{args.data.stem}_L{args.layer}_{args.pool}"
    out = args.out or (root / "results" / "safety" / f"probe_{name}")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    data = load_data(args.data, args.seed)
    feats = {}
    for split, (texts, _) in data.items():
        print(f"{split}: {len(texts)} texts", flush=True)
        feats[split] = extract(args.model, texts, args.layer, args.pool, args.batch_size, args.max_length,
                               not args.no_chat_template) if texts else np.zeros((0, 1))
    mu, sd = feats["train"].mean(0), feats["train"].std(0) + 1e-6
    norm = {s: (f - mu) / sd for s, f in feats.items()}
    best = None
    for c in (0.01, 0.1, 1.0, 10.0):
        clf = LogisticRegression(C=c, max_iter=2000).fit(norm["train"], data["train"][1])
        dev_auroc = evaluate(data["dev"][1], clf.predict_proba(norm["dev"])[:, 1], args.seed, n_boot=0)["auroc"]
        print(f"C={c}: dev AUROC {dev_auroc:.3f}", flush=True)
        if best is None or dev_auroc > best[0]:
            best = (dev_auroc, c, clf)
    _, c, clf = best
    test_scores = clf.predict_proba(norm["test"])[:, 1]
    metrics = {"test": evaluate(data["test"][1], test_scores, args.seed),
               "dev_auroc": float(best[0]), "C": c, "layer": args.layer, "pool": args.pool,
               "n_train": int(len(data["train"][1])), "feature_dim": int(feats["train"].shape[1])}
    np.savez(out / "probe.npz", coef=clf.coef_, intercept=clf.intercept_, mu=mu, sd=sd, layer=args.layer,
             pool=args.pool, model=args.model)
    save_json(out / "metrics.json", metrics)
    record = {"schema": "neurico-safety-result/v1", "job": root.name, "eval_id": f"probe:{name}",
              "category": "probe", "model_id": args.model_id or args.model, "model_access": f"hf:{args.model}",
              "runner": "script:probe.py", "task_args": {"layer": args.layer, "pool": args.pool, "data": str(args.data)},
              "judge": None, "n": metrics["test"]["n"], "metrics": {k: v for k, v in metrics["test"].items()
                                                                     if not k.endswith("_ci95")},
              "metrics_ci95": {k: v for k, v in metrics["test"].items() if k.endswith("_ci95")},
              "finished": utc_now(), "duration_s": round(time.time() - t0, 1), "status": "success",
              "artifacts": {"probe": str(out / "probe.npz"), "metrics": str(out / "metrics.json")}}
    save_json(out / "result.json", record)
    print(json.dumps(metrics["test"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
