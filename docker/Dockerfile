# syntax=docker/dockerfile:1.5
# neurico Docker Image
# Multi-stage build with NVIDIA CUDA for GPU-accelerated ML experiments
#
# User workflow:
#   1. git clone neurico
#   2. ./neurico build    <- Everything built INSIDE Docker
#   3. ./neurico run      <- Just works

ARG CUDA_VERSION=12.5.1
ARG UBUNTU_VERSION=22.04

# =============================================================================
# Stage 1: Builder - Install tools and build all environments
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS builder

LABEL org.opencontainers.image.title="neurico"
LABEL org.opencontainers.image.description="Autonomous research framework with AI agents"
LABEL org.opencontainers.image.source="https://github.com/ChicagoHAI/neurico"
LABEL maintainer="ChicagoHAI"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install system dependencies
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

# Install Node.js 22 (required for Codex and Gemini CLIs)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && rm -rf /var/lib/apt/lists/*

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# uv environment settings
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python via uv
RUN uv python install 3.12

# Install Claude Code via native installer (auto-updates in background)
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && cp /root/.local/bin/claude /usr/local/bin/claude

# Install Codex and Gemini via npm (no native Linux installer available)
RUN npm install -g @openai/codex \
    && npm install -g @google/gemini-cli

# -----------------------------------------------------------------------------
# Copy ALL code and build ALL environments inside Docker
# -----------------------------------------------------------------------------
WORKDIR /app
COPY . .

# Build neurico virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv \
    && uv sync --frozen --no-dev

# Build paper-finder virtual environment
# Note: paper-finder uses `make sync-dev` which runs `uv sync --all-packages --dev`
WORKDIR /app/services/paper-finder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-packages --dev
WORKDIR /app

# =============================================================================
# Stage 2: Runtime - Production image
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    git-lfs \
    openssh-client \
    ca-certificates \
    libcudnn8 \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install LaTeX for paper compilation (CS conference papers: NeurIPS, ICML, ACL, etc.)
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

# Copy Node.js from builder
COPY --from=builder /usr/bin/node /usr/bin/
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
RUN ln -sf /usr/lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -sf /usr/lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# Copy Claude Code native binary from builder
COPY --from=builder /usr/local/bin/claude /usr/local/bin/claude

# Symlink Codex and Gemini CLI tools (COPY dereferences symlinks, breaking Node.js relative imports)
RUN ln -sf /usr/lib/node_modules/@openai/codex/bin/codex.js /usr/bin/codex \
    && ln -sf /usr/lib/node_modules/@google/gemini-cli/dist/index.js /usr/bin/gemini

# Copy uv (agents may need to create their own environments)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Copy Python installation from builder
COPY --from=builder /python /python

# Copy the entire /app from builder (includes code AND all venvs)
COPY --from=builder /app /app

# Set up paths
ENV PATH="/app/.venv/bin:/python/bin:/usr/local/bin:${PATH}"
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed
ENV VIRTUAL_ENV="/app/.venv"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Create non-root user for security
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} researcher \
    && useradd -u ${UID} -g researcher -m -s /bin/bash researcher

# Create workspace directory (will be mounted from host)
RUN mkdir -p /workspaces && chown researcher:researcher /workspaces

# Create necessary directories and fix permissions
RUN mkdir -p /app/ideas/submitted /app/ideas/in_progress /app/ideas/completed \
    /app/logs /app/runs \
    && chown -R researcher:researcher /app \
    && chmod -R a+rX /app \
    && chmod -R 777 /app/services/paper-finder

# Switch to non-root user
USER researcher
WORKDIR /app

# Configure git for the researcher user
RUN git config --global user.email "noreply@neurico.dev" \
    && git config --global user.name "NeuriCo" \
    && git config --global init.defaultBranch main

# Create CLI tool configuration directories
# Note: Claude uses ~/.claude, Codex uses ~/.codex, Gemini uses ~/.gemini
RUN mkdir -p ~/.claude ~/.codex ~/.gemini ~/.cache/uv

# Set environment variable for workspace location
ENV NEURICO_WORKSPACE=/workspaces

VOLUME ["/workspaces"]
WORKDIR /workspaces

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["bash"]
