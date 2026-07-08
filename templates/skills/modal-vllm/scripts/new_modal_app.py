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
import importlib.util as _ilu
import re
import sys
from pathlib import Path
from string import Template
from typing import Dict

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"

KIND_TO_TEMPLATE = {
    "vllm-serve": "modal_vllm_serve.py.tmpl",
}


def slug_ok(s: str) -> bool:
    """Return True if `s` is a valid experiment slug (Modal env-name safe)."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", s))


def _find_sibling_skill_script(skill_name: str, script_name: str) -> Path:
    """Walk upward from __file__ to locate a sibling skill's script."""
    for ancestor in [HERE, *HERE.parents]:
        candidate = ancestor / skill_name / "scripts" / script_name
        if candidate.exists():
            return candidate
        candidate = ancestor / "skills" / skill_name / "scripts" / script_name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"could not locate {skill_name}/scripts/{script_name} relative to "
        f"{HERE}; install modal-training alongside modal-vllm."
    )


# Import resolve_secrets from the modal-training scaffolder so the two skills
# share one definition. Previously this function was duplicated verbatim here,
# with a comment claiming "self-contained when copied independently" — but
# this module already hard-imports modal-training/lifecycle.py, so the
# self-containment justification was always false. Load by file path with a
# unique module name to avoid the cached-vllm-module issue.
_training_scaffolder_path = _find_sibling_skill_script("modal-training", "new_modal_app.py")
_spec = _ilu.spec_from_file_location("_modal_training_scaffolder",
                                     str(_training_scaffolder_path))
_training_scaffolder = _ilu.module_from_spec(_spec)
sys.modules["_modal_training_scaffolder"] = _training_scaffolder
_spec.loader.exec_module(_training_scaffolder)  # type: ignore[union-attr]

resolve_secrets = _training_scaffolder.resolve_secrets


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
    p.add_argument("--force", action="store_true",
                   help="overwrite the destination file if it already exists")
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
    print(f"  modal deploy --env=neurico-{args.exp_id} {out}")
    print(f"  # then capture the endpoint (URL + proxy tokens):")
    print(f"  python {out} capture-endpoint")
    print(f"  # ... use it from experiment code ...")
    print(f"  # pull artifacts (redacts endpoint JSON, marks pull_complete):")
    print(f"  python .claude/skills/modal-vllm/scripts/lifecycle.py pull "
          f"--exp-id {args.exp_id}")
    print(f"  python .claude/skills/modal-vllm/scripts/lifecycle.py teardown "
          f"--exp-id {args.exp_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
