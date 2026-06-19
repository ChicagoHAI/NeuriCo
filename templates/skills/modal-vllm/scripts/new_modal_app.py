"""
Scaffolder for the modal-vllm skill.

Generates a deployable vLLM serving app from the template, wired into the
modal-vllm lifecycle.

CLI:
    python new_modal_app.py vllm-serve \\
        --exp-id workspace-slug \\
        --base-model Qwen/Qwen2.5-7B-Instruct \\
        --lora-repo user/my-adapter \\
        --gpu L40S:1 \\
        --out src/modal_serve.py
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
    "vllm-serve": "modal_vllm_serve.py.tmpl",
}


def slug_ok(s: str) -> bool:
    """Return True if `s` is a valid experiment slug (Modal env-name safe)."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", s))


# Shared with modal-training scaffolder. Duplicated here so this skill stays
# self-contained when copied into a workspace independently.
def resolve_secrets(
    secret_args: List[str],
    include_hf_default: bool,
) -> Tuple[str, str]:
    """
    Resolve --secret flags into (SECRETS_LIST, REQUIRED_SECRETS) literals.

    See modal-training/scripts/new_modal_app.py:resolve_secrets for the full
    contract and rationale.
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
    p = argparse.ArgumentParser(description="scaffold a Modal vLLM serving app")
    p.add_argument("kind", choices=sorted(KIND_TO_TEMPLATE.keys()))
    p.add_argument("--exp-id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--base-model-revision", default="main")
    p.add_argument("--lora-repo", default="",
                   help="HF repo id of LoRA adapter to hot-load (optional)")
    p.add_argument("--gpu", default="L40S:1")
    p.add_argument("--max-model-len", type=int, default=8192)
    p.add_argument("--max-lora-rank", type=int, default=32)
    p.add_argument("--scaledown-minutes", type=int, default=20)
    p.add_argument("--share-hf-cache", action="store_true")
    p.add_argument("--no-hf-secret", action="store_true",
                   help="drop the default huggingface-secret entry (public "
                        "models, or when HF_TOKEN is unset locally)")
    p.add_argument("--secret", action="append", default=[],
                   metavar="NAME=ENV_VAR[,ENV_VAR2]",
                   help="add a Modal secret to provision per-experiment "
                        "(repeatable); see modal-training scaffolder for the "
                        "full contract")
    args = p.parse_args()

    if not slug_ok(args.exp_id):
        print(f"error: --exp-id {args.exp_id!r} must match "
              f"[a-z0-9][a-z0-9-]{{0,62}}", file=sys.stderr)
        return 2

    hf_volume = ("neurico-hf-cache" if args.share_hf_cache
                 else f"neurico-{args.exp_id}-hf")

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
        "LORA_REPO": args.lora_repo,
        "GPU": args.gpu,
        "MAX_MODEL_LEN": str(args.max_model_len),
        "MAX_LORA_RANK": str(args.max_lora_rank),
        "SCALEDOWN_MINUTES": str(args.scaledown_minutes),
        "HF_VOLUME": hf_volume,
        "VLLM_CACHE_VOLUME": f"neurico-{args.exp_id}-vllm-cache",
        "SHARE_HF_CACHE": "True" if args.share_hf_cache else "False",
        "APP_NAME": f"neurico-{args.exp_id}-vllm",
        "SECRETS_LIST": secrets_list_literal,
        "REQUIRED_SECRETS": required_secrets_literal,
    }

    rendered = render(args.kind, subs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {out}")
    print()
    print("next steps:")
    print(f"  modal deploy --env=neurico-{args.exp_id} {out}")
    print(f"  # then capture the endpoint (URL + proxy tokens):")
    print(f"  python {out} capture-endpoint")
    print(f"  # ... use it from experiment code ...")
    print(f"  python .claude/skills/modal-vllm/scripts/lifecycle.py teardown "
          f"--exp-id {args.exp_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
