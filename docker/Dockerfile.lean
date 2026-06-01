# syntax=docker/dockerfile:1.5
# neurico-lean Docker Image
# Extends chicagohai/neurico with Lean 4 formal verification support.
#
# Adds on top of the standard neurico stack:
#   - libgmp-dev  (required by Lean's kernel)
#   - elan        (Lean version manager)
#   - lean        (Lean 4 proof assistant, Mathlib-pinned toolchain)
#   - lake        (Lean build tool)
#   - Mathlib.Tactic olean cache (~1-2GB, pre-warmed at build time)
#
# One build command:
#   docker build -f docker/Dockerfile.lean -t chicagohai/neurico-lean:latest .
#
# Or pull the pre-built image:
#   docker pull ghcr.io/chicagohai/neurico-lean:latest

# Lean 4 only provides pre-built binaries for x86_64-linux.
# Pin to linux/amd64 so this image builds and runs correctly on any host,
# including Apple Silicon Macs (where Docker Desktop defaults to aarch64).
FROM --platform=linux/amd64 ghcr.io/chicagohai/neurico:latest

# Switch to root to install system packages
USER root

# libgmp-dev is required by Lean's kernel (arbitrary-precision arithmetic)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Switch back to non-root user for all Lean installation
USER neurico

LABEL org.opencontainers.image.title="neurico-lean"
LABEL org.opencontainers.image.description="Autonomous research framework with Lean 4 formal verification"
LABEL org.opencontainers.image.source="https://github.com/ChicagoHAI/neurico"
LABEL maintainer="ChicagoHAI"

ENV ELAN_HOME=/home/neurico/.elan
ENV PATH="${ELAN_HOME}/bin:${PATH}"

# Install elan and the Lean toolchain pinned by current Mathlib.
# elan only ships binaries for leanprover/lean4 releases — fetching the version
# from Mathlib's lean-toolchain file gives the exact release Mathlib4 requires.
RUN LEAN_TOOLCHAIN=$(curl -fsSL \
        https://raw.githubusercontent.com/leanprover-community/mathlib4/master/lean-toolchain \
      | tr -d '[:space:]') \
    && curl -sSfL \
         https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y \
         --no-modify-path \
         --default-toolchain "$LEAN_TOOLCHAIN" \
    && lean --version \
    && lake --version

# Pre-warm the Mathlib.Tactic olean cache (~1-2GB).
# Runs at build time so standalone containers need no network access for Lean.
# Force HTTP/1.1 to prevent git clone stalls in WSL2/Docker (HTTP/2 multiplexing
# causes hangs on some network configurations).
RUN git config --global http.version HTTP/1.1 \
    && git config --global http.postBuffer 524288000 \
    && mkdir -p /tmp/lean-warmup \
    && cd /tmp/lean-warmup \
    && lake new warmup math \
    && cd warmup \
    && printf 'import Mathlib.Tactic\n\nnamespace Warmup\nend Warmup\n' \
         > Warmup.lean \
    && lake exe cache get \
    && lake build \
    && cd / && rm -rf /tmp/lean-warmup

# Smoke-test: verify lean can compile a simple theorem
RUN echo 'theorem smoke (n : Nat) : n + 0 = n := Nat.add_zero n' | lean --stdin

VOLUME ["/workspaces"]
WORKDIR /workspaces

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD lean --version

ENTRYPOINT ["/app/docker/entrypoint.lean.sh"]
CMD ["bash"]
