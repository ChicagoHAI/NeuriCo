"""Locked ``codex`` launcher for Harbor's Python-only source runtime."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


CODEX_VERSION = "0.147.0"
NVM_VERSION = "0.40.2"


def _ensure_git_available() -> None:
    """Install Git when the minimal Harbor task image does not provide it."""
    if shutil.which("git") is not None:
        return
    if os.geteuid() != 0:
        raise RuntimeError(
            "NeuriCo AutoResearch requires git; install it in the Harbor task image "
            "or run the source agent as a user allowed to install system packages"
        )

    installers = (
        ("apt-get", ["apt-get", "install", "-y", "-qq", "git"]),
        ("apk", ["apk", "add", "--no-cache", "git"]),
        ("dnf", ["dnf", "install", "-y", "git"]),
        ("yum", ["yum", "install", "-y", "git"]),
    )
    for command, arguments in installers:
        if shutil.which(command) is not None:
            subprocess.run(arguments, check=True, stdout=sys.stderr, stderr=sys.stderr)
            if shutil.which("git") is not None:
                return
            break
    raise RuntimeError("NeuriCo AutoResearch requires git, but it could not be installed")


def _reported_version(executable: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text.removeprefix("codex-cli").strip() or None


def _existing_codex() -> Path | None:
    explicit = os.environ.get("NEURICO_CODEX_EXECUTABLE")
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError("NEURICO_CODEX_EXECUTABLE must name an existing absolute file")
        return path

    launcher_dir = Path(sys.argv[0]).resolve().parent
    search_path = os.pathsep.join(
        entry
        for entry in os.environ.get("PATH", os.defpath).split(os.pathsep)
        if Path(entry).resolve() != launcher_dir
    )
    found = shutil.which("codex", path=search_path)
    if found is None:
        return None
    candidate = Path(found).resolve()
    if _reported_version(candidate) != CODEX_VERSION:
        return None
    return candidate


def _cache_root() -> Path:
    configured = os.environ.get("NEURICO_CODEX_CACHE")
    root = Path(configured) if configured else Path.home() / ".cache" / "neurico-codex"
    if not root.is_absolute():
        raise RuntimeError("NEURICO_CODEX_CACHE must be an absolute path")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _activate_cached_node(root: Path) -> None:
    """Expose an NVM-installed Node binary to npm's Codex launcher."""
    node_root = root / f"nvm-{NVM_VERSION}" / "versions" / "node"
    node_bins = sorted(node_root.glob("*/bin"))
    if not node_bins:
        return
    node_bin = node_bins[-1]
    current_path = os.environ.get("PATH", os.defpath)
    path_entries = current_path.split(os.pathsep)
    if str(node_bin) not in path_entries:
        os.environ["PATH"] = f"{node_bin}{os.pathsep}{current_path}"


def _install_with_npm(root: Path) -> Path:
    _activate_cached_node(root)
    prefix = root / f"codex-{CODEX_VERSION}"
    executable = prefix / "node_modules" / ".bin" / "codex"
    if executable.is_file() and _reported_version(executable) == CODEX_VERSION:
        return executable

    npm = shutil.which("npm")
    if npm is not None:
        subprocess.run(
            [
                npm,
                "install",
                "--no-audit",
                "--no-fund",
                "--omit=dev",
                "--prefix",
                str(prefix),
                f"@openai/codex@{CODEX_VERSION}",
            ],
            check=True,
        )
    else:
        nvm_dir = root / f"nvm-{NVM_VERSION}"
        nvm_script = nvm_dir / "nvm.sh"
        if not nvm_script.is_file():
            nvm_dir.mkdir(parents=True, exist_ok=True)
            url = (
                "https://raw.githubusercontent.com/nvm-sh/nvm/"
                f"v{NVM_VERSION}/install.sh"
            )
            with tempfile.NamedTemporaryFile(prefix="install-nvm-", suffix=".sh") as script:
                with urllib.request.urlopen(url, timeout=60) as response:
                    shutil.copyfileobj(response, script)
                script.flush()
                install_environment = dict(os.environ)
                install_environment.update({"NVM_DIR": str(nvm_dir), "PROFILE": "/dev/null"})
                subprocess.run(
                    ["bash", script.name],
                    check=True,
                    env=install_environment,
                )

        command = (
            'set -euo pipefail; source "$NVM_DIR/nvm.sh"; '
            "nvm install 22; "
            f'npm install --no-audit --no-fund --omit=dev --prefix "$CODEX_PREFIX" '
            f"@openai/codex@{CODEX_VERSION}"
        )
        install_environment = dict(os.environ)
        install_environment.update(
            {
                "NVM_DIR": str(nvm_dir),
                "CODEX_PREFIX": str(prefix),
                "NVM_NODEJS_ORG_MIRROR": "https://nodejs.org/dist",
            }
        )
        subprocess.run(["bash", "-lc", command], check=True, env=install_environment)
        _activate_cached_node(root)

    if not executable.is_file() or _reported_version(executable) != CODEX_VERSION:
        raise RuntimeError(f"Failed to install Codex CLI {CODEX_VERSION}")
    return executable


def resolve_codex() -> Path:
    """Resolve an explicitly supplied or exactly pinned Codex executable."""
    existing = _existing_codex()
    if existing is not None:
        return existing

    root = _cache_root()
    lock_path = root / ".install.lock"
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return _install_with_npm(root)


def main() -> None:
    _ensure_git_available()
    executable = resolve_codex()
    os.execvpe(str(executable), [str(executable), *sys.argv[1:]], os.environ)


if __name__ == "__main__":
    main()
