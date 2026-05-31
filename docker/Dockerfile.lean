# syntax=docker/dockerfile:1.5
# =============================================================================
# neurico-lean — Standalone Lean 4 research image
#
# Self-contained: builds from the upstream CUDA base directly.
# No dependency on a pre-built chicagohai/neurico image.
#
# One build command:
#   docker build -f docker/Dockerfile.lean -t chicagohai/neurico-lean:latest .
#
# Adds on top of the standard neurico stack:
#   - elan  (Lean version manager)
#   - lean  (Lean 4 proof assistant, Mathlib-pinned toolchain)
#   - lake  (Lean build tool)
#   - Mathlib.Tactic olean cache (~1-2GB, pre-warmed at build time)
#     so each standalone run needs no network access for Lean.
# =============================================================================

ARG CUDA_VERSION=12.5.1
ARG UBUNTU_VERSION=22.04

# Lean 4 only provides pre-built binaries for x86_64-linux.
# Pin to linux/amd64 so this image builds and runs correctly on any host,
# including Apple Silicon Macs (where Docker Desktop defaults to aarch64).
ARG TARGETPLATFORM=linux/amd64

# =============================================================================
# Stage 1: Builder — install tools and build all Python environments
# =============================================================================
FROM --platform=linux/amd64 nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS builder

LABEL org.opencontainers.image.title="neurico-lean"
LABEL org.opencontainers.image.description="Autonomous research framework with Lean 4 formal verification"
LABEL org.opencontainers.image.source="https://github.com/ChicagoHAI/neurico"
LABEL maintainer="ChicagoHAI"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# System dependencies (same as base image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    libssl-dev \
    libffi-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev \
    liblzma-dev \
    zlib1g-dev \
    git-lfs \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 (for Codex and Gemini CLIs)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed

RUN uv python install 3.12

# Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && cp /root/.local/bin/claude /usr/local/bin/claude

# Codex and Gemini CLIs
RUN npm install -g @openai/codex \
    && npm install -g @google/gemini-cli

# Build neurico app and all virtual environments
WORKDIR /app
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv \
    && uv sync --frozen --no-dev

WORKDIR /app/services/paper-finder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-packages --dev
WORKDIR /app

# =============================================================================
# Stage 2: Runtime — production image with Lean 4 added
# =============================================================================
FROM --platform=linux/amd64 nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    git-lfs \
    openssh-client \
    ca-certificates \
    libcudnn8 \
    make \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# LaTeX for paper compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-science \
    texlive-bibtex-extra \
    texlive-publishers \
    lmodern \
    cm-super \
    biber \
    latexmk \
    && rm -rf /var/lib/apt/lists/*

# Node.js from builder
COPY --from=builder /usr/bin/node /usr/bin/
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
RUN ln -sf /usr/lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -sf /usr/lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# Claude Code CLI
COPY --from=builder /usr/local/bin/claude /usr/local/bin/claude

# Codex and Gemini
RUN ln -sf /usr/lib/node_modules/@openai/codex/bin/codex.js /usr/bin/codex \
    && ln -sf /usr/lib/node_modules/@google/gemini-cli/bundle/gemini.js /usr/bin/gemini

# uv
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Non-root user
RUN useradd -u 1000 -m -s /bin/bash neurico

# Python and app
COPY --from=builder /python /python
COPY --from=builder --chown=neurico:neurico /app /app

ENV PATH="/app/.venv/bin:/python/bin:/usr/local/bin:${PATH}"
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed
ENV VIRTUAL_ENV="/app/.venv"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONPATH="/app:${PYTHONPATH}"

RUN mkdir -p /workspaces \
    /app/ideas/submitted /app/ideas/in_progress /app/ideas/completed \
    /app/logs /app/runs

# ── Lean 4 installation (as neurico user) ─────────────────────────────────────
USER neurico
WORKDIR /app

RUN git config --global user.email "noreply@neurico.dev" \
    && git config --global user.name "NeuriCo" \
    && git config --global init.defaultBranch main \
    && mkdir -p ~/.claude ~/.codex ~/.gemini ~/.cache/uv \
    && echo 'PS1="neurico:\w\$ "' >> ~/.bashrc

ENV ELAN_HOME=/home/neurico/.elan
ENV PATH="${ELAN_HOME}/bin:${PATH}"
ENV NEURICO_WORKSPACE=/workspaces

# Install elan and the Mathlib-pinned Lean toolchain
RUN curl -sSfL \
      https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y \
        --no-modify-path \
        --default-toolchain leanprover-community/mathlib4:stable \
    && lean --version \
    && lake --version

# Pre-warm the Mathlib.Tactic olean cache (~1-2GB).
# Runs at build time so standalone containers need no network access for Lean.
RUN mkdir -p /tmp/lean-warmup \
    && lake +leanprover-community/mathlib4:stable \
         init /tmp/lean-warmup/warmup math \
    && cd /tmp/lean-warmup/warmup \
    && printf 'import Mathlib.Tactic\n\nnamespace Warmup\nend Warmup\n' \
         > LeanProofs/Definitions.lean \
    && lake exe cache get \
    && lake build \
    && rm -rf /tmp/lean-warmup

# Smoke-test: verify lean can compile a simple theorem
RUN lean --stdin <<< 'theorem smoke (n : Nat) : n + 0 = n := Nat.add_zero n'

VOLUME ["/workspaces"]
WORKDIR /workspaces

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD lean --version

ENTRYPOINT ["/app/docker/entrypoint.lean.sh"]
CMD ["bash"]
