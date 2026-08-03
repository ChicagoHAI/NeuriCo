"""Encryption at rest for sealed held-out data.

Sealed datasets in continue-research are genuinely secret: their whole value is
that the model under study has never seen them. The sealed store, however, is a
sibling under the workspaces root and rides the same Docker mount into the
research container, so an agent can list and read it. We therefore make what the
agent can read useless: the store holds only CIPHERTEXT. The scorer decrypts
transiently into the throwaway scoring worktree; the live workspace never holds
plaintext held-out data.

Key handling. The key is a launch secret, ``NEURICO_SEAL_KEY`` (a Fernet key,
managed like a provider API key in the run's .env). The runner reads it once and
POPS it out of ``os.environ``; it lives only in this module's memory thereafter.
Every agent subprocess is spawned with ``os.environ.copy()``, so once the key is
popped no agent process inherits it, and it is never written to a file under the
workspace.

Threat model. This defends against reward-hacking: an agent opportunistically
reading held-out data it can see. It does NOT defend against a determined agent
scraping the runner's process memory for the key mid-scoring; that is out of
scope for this model. If it ever comes into scope, run the agent as a separate
OS user or move scoring into its own container.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

SEAL_KEY_ENV = "NEURICO_SEAL_KEY"


class SealKeyMissing(RuntimeError):
    """Raised when sealed data needs the key but NEURICO_SEAL_KEY is unset."""


# Read from the environment exactly once, cached here, and removed from
# os.environ so agent subprocesses (os.environ.copy()) never inherit it.
_key_cache: Optional[bytes] = None
_key_loaded = False


def load_seal_key() -> Optional[bytes]:
    """Return the seal key, reading-and-removing it from the environment once.

    Idempotent: after the first call the key is gone from os.environ, so any
    later os.environ.copy() (used for every agent spawn) is keyless. Safe to
    call eagerly at runner startup and lazily at each encrypt/decrypt.
    """
    global _key_cache, _key_loaded
    if not _key_loaded:
        raw = os.environ.pop(SEAL_KEY_ENV, None)
        _key_cache = raw.strip().encode("utf-8") if raw and raw.strip() else None
        _key_loaded = True
    return _key_cache


def seal_key_available() -> bool:
    return load_seal_key() is not None


def generate_key() -> str:
    """A fresh Fernet key string, for the launcher to persist as a secret."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


def _fernet():
    from cryptography.fernet import Fernet

    key = load_seal_key()
    if key is None:
        raise SealKeyMissing(
            f"{SEAL_KEY_ENV} is not set, but this run declares sealed held-out "
            "data that must be encrypted at rest. Generate a key with\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            f"and add it to your run .env as {SEAL_KEY_ENV}=<key> (keep it like "
            "a provider key; a lost key means re-staging the store from source)."
        )
    return Fernet(key)


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _fernet().decrypt(token)


def encrypt_file_in_place(path: Path) -> None:
    """Replace a plaintext file with its ciphertext."""
    p = Path(path)
    p.write_bytes(encrypt(p.read_bytes()))


def decrypt_to(src: Path, dst: Path) -> None:
    """Write the decrypted plaintext of ciphertext file ``src`` to ``dst``."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(decrypt(Path(src).read_bytes()))


def default_env_path() -> Path:
    """The run's .env (install root), matching runner.main()'s dotenv load."""
    return Path(__file__).resolve().parent.parent.parent / ".env"


def _append_seal_key_to_env(env_path: Path, key: str) -> None:
    """Persist NEURICO_SEAL_KEY=<key> to the .env, without duplicating it."""
    env_path = Path(env_path)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for row in existing.splitlines():
        if row.strip().startswith(f"{SEAL_KEY_ENV}="):
            return
    env_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}{SEAL_KEY_ENV}={key}\n")


def ensure_seal_key(env_path: Optional[Path] = None) -> None:
    """Provision a key when none is set.

    Generate a random per-user key, persist it to the run's .env (the host-only
    secret store, already stripped from agent env at startup), and load it for
    this process. A random key, not a shared constant, so nothing secret is
    baked into the repo, and the user can override by setting their own. A lost
    key just means re-staging the store from source. Idempotent.
    """
    global _key_cache, _key_loaded
    if seal_key_available():
        return
    key = generate_key()
    target = Path(env_path) if env_path is not None else default_env_path()
    _append_seal_key_to_env(target, key)
    # Usable in this process; deliberately NOT written to os.environ, so agent
    # subprocesses (os.environ.copy()) still never inherit it.
    _key_cache = key.encode("utf-8")
    _key_loaded = True
    print(
        f"🔑 No {SEAL_KEY_ENV} set; generated one and saved it to {target}. "
        f"Sealed held-out data is encrypted at rest with it. Keep this key (a "
        f"lost key means re-staging the store); set your own to override."
    )


def require_key_for_sealed(has_sealed_data: bool,
                           env_path: Optional[Path] = None) -> None:
    """When sealed data is declared, ensure a key exists, provisioning a fresh
    one into the .env if the user set none."""
    if has_sealed_data:
        ensure_seal_key(env_path)
