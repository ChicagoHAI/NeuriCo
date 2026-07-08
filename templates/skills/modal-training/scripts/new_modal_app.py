"""
Scaffolder for the modal-training skill.

Picks a template, fills in EXP_ID + per-experiment volume names, writes
the result to a destination file. Generated scripts call
lifecycle.register() on import so the env is created (and secrets minted)
before any Modal call runs — the template cannot accidentally bypass the
lifecycle.

CLI:
    python new_modal_app.py lora-train \\
        --exp-id workspace-slug \\
        --base-model Qwen/Qwen2.5-7B-Instruct \\
        --dataset /data/train.jsonl \\
        --out src/modal_train.py

    python new_modal_app.py data-prep --exp-id ... --out src/modal_prep.py
    python new_modal_app.py eval      --exp-id ... --out src/modal_eval.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from string import Template
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"

KIND_TO_TEMPLATE = {
    "lora-train": "modal_lora_train.py.tmpl",
    "data-prep":  "modal_data_prep.py.tmpl",
    "eval":       "modal_eval.py.tmpl",
}


def slug_ok(s: str) -> bool:
    """Return True if `s` is a valid experiment slug (Modal env-name safe)."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", s))


def resolve_secrets(
    secret_args: List[str],
    include_hf_default: bool,
) -> Tuple[str, str]:
    """
    Resolve --secret flags into the two Python literals the templates need.

    Returns (secrets_list_literal, required_secrets_literal):
      secrets_list_literal      — Python source for `secrets=[...]` decorator
                                  arg (used by Modal at function dispatch)
      required_secrets_literal  — Python source for `register(required_secrets=...)`
                                  (used by lifecycle to mint secrets per-env)

    The two are derived from the same resolved set so they cannot diverge:
    every secret minted gets mounted, and vice versa.

    --secret entries are of the form NAME=ENV_VAR[,ENV_VAR2]. They are
    additive on top of the default set; pass --no-hf-secret to drop the HF
    entry from the default.
    """
    resolved: Dict[str, List[str]] = {}
    if include_hf_default:
        resolved["huggingface-secret"] = ["HF_TOKEN"]

    for spec in secret_args:
        if "=" not in spec:
            raise ValueError(
                f"--secret {spec!r}: expected NAME=ENV_VAR[,ENV_VAR2]"
            )
        name, _, vars_csv = spec.partition("=")
        name = name.strip()
        env_vars = [v.strip() for v in vars_csv.split(",") if v.strip()]
        if not name or not env_vars:
            raise ValueError(
                f"--secret {spec!r}: name and at least one env var required"
            )
        resolved[name] = env_vars

    if not resolved:
        return "[]", "{}"

    secrets_list = "[" + ", ".join(
        f'modal.Secret.from_name("{name}")' for name in resolved
    ) + "]"
    return secrets_list, json.dumps(resolved)


def render(kind: str, subs: Dict[str, str]) -> str:
    """Read the requested template and apply ${VAR} substitutions."""
    tmpl_path = TEMPLATES_DIR / KIND_TO_TEMPLATE[kind]
    if not tmpl_path.exists():
        raise FileNotFoundError(f"template missing: {tmpl_path}")
    return Template(tmpl_path.read_text(encoding="utf-8")).substitute(subs)


def main() -> int:
    p = argparse.ArgumentParser(description="scaffold a Modal training app")
    p.add_argument("kind", choices=sorted(KIND_TO_TEMPLATE.keys()))
    p.add_argument("--exp-id", required=True,
                   help="experiment slug — must match [a-z0-9][a-z0-9-]{0,62}")
    p.add_argument("--out", required=True, help="destination path")
    p.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--base-model-revision", default="main")
    p.add_argument("--dataset", default="/data/train.jsonl",
                   help="path inside the data volume to read training rows from")
    p.add_argument("--val-dataset", default="/data/val.jsonl")
    p.add_argument("--gpu", default="L40S:1",
                   help="modal GPU spec; agent picks per experiment "
                        "(L40S:1, H100:1, A100-80GB:1, etc.)")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--rank", type=int, default=16,
                   help="LoRA rank; 0 = full SFT (not supported by all templates)")
    p.add_argument("--max-steps", type=int, default=2000)
    p.add_argument("--max-seq-len", type=int, default=2048)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--share-hf-cache", action="store_true",
                   help="reuse a workspace-wide HF cache volume instead of "
                        "per-experiment (defaults to per-experiment / strict)")
    p.add_argument("--no-hf-secret", action="store_true",
                   help="drop the default huggingface-secret entry (use for "
                        "fully-public models/datasets, or when local "
                        "HF_TOKEN is unset)")
    p.add_argument("--secret", action="append", default=[],
                   metavar="NAME=ENV_VAR[,ENV_VAR2]",
                   help="add a Modal secret to provision per-experiment "
                        "(repeatable). Example: --secret "
                        "wandb-secret=WANDB_API_KEY. The lifecycle reads the "
                        "named local env vars and mints the secret into "
                        "neurico-<EXP_ID> at register() time.")
    p.add_argument("--force", action="store_true",
                   help="overwrite the destination file if it already exists")
    args = p.parse_args()

    if not slug_ok(args.exp_id):
        print(f"error: --exp-id {args.exp_id!r} must match "
              f"[a-z0-9][a-z0-9-]{{0,62}}", file=sys.stderr)
        return 2

    hf_volume = ("neurico-hf-cache" if args.share_hf_cache
                 else f"neurico-{args.exp_id}-hf")

    # Resolve the requested secret set into the two literals the templates
    # need. SECRETS_LIST goes into @app.function(secrets=[...]) so Modal
    # mounts them at dispatch time; REQUIRED_SECRETS goes into
    # lifecycle.register(required_secrets=...) so the lifecycle mints them
    # into the per-experiment env from local env vars. They are derived
    # from the same resolved set so they cannot diverge.
    try:
        secrets_list_literal, required_secrets_literal = resolve_secrets(
            args.secret, include_hf_default=not args.no_hf_secret,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    subs = {
        "EXP_ID": args.exp_id,
        "BASE_MODEL": args.base_model,
        "BASE_MODEL_REVISION": args.base_model_revision,
        "GPU": args.gpu,
        "EPOCHS": str(args.epochs),
        "LR": str(args.lr),
        "RANK": str(args.rank),
        "ALPHA": str(args.rank * 2),
        "MAX_STEPS": str(args.max_steps),
        "MAX_SEQ_LEN": str(args.max_seq_len),
        "BATCH_SIZE": str(args.batch_size),
        "GRAD_ACCUM": str(args.grad_accum),
        "TRAIN_FILE": args.dataset,
        "VAL_FILE": args.val_dataset,
        "DATA_VOLUME": f"neurico-{args.exp_id}-data",
        "CKPT_VOLUME": f"neurico-{args.exp_id}-ckpts",
        "HF_VOLUME": hf_volume,
        "SHARE_HF_CACHE": "True" if args.share_hf_cache else "False",
        "APP_NAME": f"neurico-{args.exp_id}-{args.kind.replace('-', '_')}",
        "SECRETS_LIST": secrets_list_literal,
        "REQUIRED_SECRETS": required_secrets_literal,
    }

    rendered = render(args.kind, subs)
    out = Path(args.out)
    if out.exists() and not args.force:
        print(
            f"error: {out} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {out}")
    print()
    print("next steps:")
    print(f"  modal run --env=neurico-{args.exp_id} {out} \\")
    print(f"      2>&1 | tee logs/modal_{args.kind}_$(date +%Y%m%d_%H%M%S).log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
