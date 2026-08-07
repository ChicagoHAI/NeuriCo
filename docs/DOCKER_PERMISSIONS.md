# Docker Permissions Design

> **Developer/internal document.** This describes Docker's mount and permission
> implementation. It is not required for normal setup; use it when maintaining
> or diagnosing the container boundary.

This document explains how NeuriCo handles file permissions between the host machine and Docker containers, the reasoning behind the current design, and known tradeoffs.

## The Core Problem

NeuriCo runs AI agents (Claude Code, Codex, Gemini) inside Docker containers. The container has a built-in user `neurico` with **uid 1000**. On many machines (especially shared servers), the host user has a different uid (e.g., 19173). When host directories are bind-mounted into the container, the container user cannot read or write files owned by a different uid if permissions are restrictive (e.g., `600` = owner-only).

This causes:
- **Claude Code hanging on startup** — it silently hangs when it can't read `~/.claude/.credentials.json`
- **Paper-finder "Permission denied"** — can't write to `/app/logs/paper-finder.log` when the host `logs/` dir is owned by a different uid
- **Codex permission errors** — `Error loading config.toml: Permission denied`

## Why uid 1000?

The Dockerfile creates user `neurico` with uid 1000 (`useradd -u 1000 -m -s /bin/bash neurico`). This is the conventional default uid for the first non-root user on Linux systems. On many single-user machines (e.g., Google Cloud VMs), the host user is also uid 1000, so everything works without permission adjustments. On shared servers (e.g., university machines), users typically have higher uids assigned by a central directory service.

## Current Approach

### Host-side permissions (`docker/run.sh`)

The `ensure_directories()` function runs before every `docker run` command. It creates required directories and adjusts permissions:

```bash
ensure_directories() {
    # Create directories
    mkdir -p "$workspace_dir"
    mkdir -p "$PROJECT_ROOT/logs"
    mkdir -p "$PROJECT_ROOT/ideas/submitted" ...

    # Make project directory world-accessible for container
    chmod -R a+rwX "$PROJECT_ROOT" 2>/dev/null || true

    # Workspace may be outside PROJECT_ROOT
    chmod -R a+rwX "$workspace_dir" 2>/dev/null || true

    # CLI credential dirs (OAuth tokens for Claude/Codex/Gemini)
    chmod -R a+rwX "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini" 2>/dev/null || true

    # Lock down .env (contains raw API keys)
    chmod 600 "$PROJECT_ROOT/.env" 2>/dev/null || true
}
```

Additionally, `cmd_login()` and `setup_login_provider()` chmod credential directories after creating them with `mkdir -p`, since `ensure_directories()` may have run before the directories existed.

### Container-side safety net (`docker/entrypoint.sh`)

The entrypoint adds a fallback chmod for `/app/logs` in case someone runs Docker directly without going through `run.sh`:

```bash
mkdir -p /app/logs
chmod -R a+rwX /app/logs 2>/dev/null || true
```

### What gets `a+rwX` (world read/write)

| Directory | Why |
|-----------|-----|
| `$PROJECT_ROOT` (NeuriCo folder) | Container needs to read config, templates, write logs, ideas |
| `$workspace_dir` | May be outside PROJECT_ROOT (configurable in `config/workspace.yaml`) |
| `~/.claude`, `~/.codex`, `~/.gemini` | Container reads credentials for auth, writes new ones during login |

### What gets locked down

| File | Permissions | Why |
|------|-------------|-----|
| `$PROJECT_ROOT/.env` | `600` (owner-only) | Contains raw API keys (OpenAI, GitHub, etc.) that can be directly used |

### Risk assessment of credential dirs

The CLI credential directories (`~/.claude`, `~/.codex`, `~/.gemini`) contain **OAuth tokens** from browser-based login sessions. These are lower risk than `.env` because:
- They expire and can be revoked by logging out
- They're tied to specific CLI tool sessions
- Someone would need to know how to extract and replay them
- They don't provide general-purpose API access

In contrast, `.env` contains raw API keys (OpenAI, GitHub, Anthropic, etc.) that can be directly used from anywhere, which is why it gets `600` permissions.

## Previous Approaches (and why they were abandoned)

### `--user $(id -u):$(id -g)` (removed in commit `fbace50`)

The initial approach ran the container as the host user's uid:

```bash
get_user_flags() {
    echo "--user $(id -u):$(id -g)"
}
```

**Problems:**
- No `/etc/passwd` entry for arbitrary uids — tools like `git` produce warnings
- `HOME` isn't set correctly for non-existent users, defaults to `/`
- Claude Code scans the entire filesystem when started from `/`, causing hangs
- Required `-e HOME=/tmp` workaround, which meant credentials had to be mounted at `/tmp/.claude` instead of `~/.claude`
- Created confusion with two different mount paths depending on context

### Selective chmod (replaced by project-wide chmod)

Originally, only specific directories were chmod'd:

```bash
chmod -R a+rwX "$workspace_dir" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/ideas"
chmod -R a+rX "$PROJECT_ROOT/config" "$PROJECT_ROOT/templates"
```

**Problem:** Easy to miss directories. When new features added new paths (e.g., paper-finder logs), they'd hit permission errors. Simpler to chmod the entire project root and just lock down `.env`.

## Login Flow

Two login paths exist:

1. **`./neurico login`** (`cmd_login()`) — mounts credentials at `/home/neurico/.claude` (container user's home)
2. **Setup wizard** (`setup_login_provider()`) — mounts credentials at `/tmp/.claude` with `CLAUDE_CONFIG_DIR` env var

Both set `NEURICO_LOGIN_ONLY=1` to skip paper-finder startup for faster login.

## Docker-compose vs run.sh

`docker-compose.yml` mounts credentials as read-only (`:ro`) to `/tmp/.claude`:
```yaml
- ~/.claude:/tmp/.claude:ro
```

`run.sh` mounts as read-write to `/home/neurico/.claude`:
```bash
-v "$HOME/.claude:/home/neurico/.claude"
```

The `docker-compose.yml` is not used by the `./neurico` CLI — it exists as an alternative for users who prefer docker-compose. The mount path difference (`/tmp` vs `/home/neurico`) is handled by the `CLAUDE_CONFIG_DIR` environment variable.

## Future Improvements

### 1. Use `--user` with proper passwd handling

A more robust approach would run the container as the host uid while providing a valid passwd entry:

```bash
docker run --user $(id -u):$(id -g) \
    -v /etc/passwd:/etc/passwd:ro \
    -e HOME=/home/neurico \
    ...
```

This would eliminate the need to chmod credential directories, since the container process would run as the same uid that owns the files. The tradeoff is complexity and potential issues with tools that expect a writable home directory.

### 2. User namespace remapping

Docker's `userns-remap` feature can map container uid 1000 to the host uid automatically. This requires Docker daemon configuration and may not be available on all systems.

### 3. Consistent mount paths

Currently, credentials are mounted to different paths depending on context (`/home/neurico/.claude` vs `/tmp/.claude`). Standardizing on one path and using `CLAUDE_CONFIG_DIR` consistently would reduce confusion.

### 4. Credential encryption at rest

Instead of relying on file permissions, credentials could be encrypted on the host and decrypted inside the container using a session key. This would eliminate the shared-server risk entirely, but adds significant complexity.
