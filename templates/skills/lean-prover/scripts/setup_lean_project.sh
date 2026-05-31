#!/usr/bin/env bash
# Setup a Lean 4 + Mathlib project in lean_proofs/ within the current workspace.
# Usage: bash .claude/skills/lean-prover/scripts/setup_lean_project.sh
set -euo pipefail

PROJECT_DIR="${1:-lean_proofs}"
LIB_NAME="LeanProofs"

echo "========================================"
echo "  Lean 4 + Mathlib Project Setup"
echo "  Target: $PROJECT_DIR/"
echo "========================================"

# ── 1. Install elan if not present ───────────────────────────────────────────
if ! command -v elan &>/dev/null && ! command -v lean &>/dev/null; then
  echo ""
  echo "► Installing elan (Lean version manager)..."
  curl -sSfL \
    https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none
  # shellcheck source=/dev/null
  source "$HOME/.elan/env" 2>/dev/null || export PATH="$HOME/.elan/bin:$PATH"
  echo "  elan installed."
else
  echo "► elan/lean already installed: $(elan --version 2>/dev/null || lean --version)"
fi

# ── 2. Create project directory ───────────────────────────────────────────────
if [ -d "$PROJECT_DIR" ]; then
  echo ""
  echo "► Directory '$PROJECT_DIR' already exists — skipping creation."
else
  echo ""
  echo "► Creating Lean project with Mathlib..."
  # Use the official mathlib4 template so the toolchain pin is correct
  lake +leanprover-community/mathlib4:stable init "$PROJECT_DIR" math
  echo "  Project created."
fi

cd "$PROJECT_DIR"

# ── 3. Create library source directory ───────────────────────────────────────
mkdir -p "$LIB_NAME"

# ── 4. Write starter files (only if they don't exist yet) ────────────────────
if [ ! -f "$LIB_NAME/Definitions.lean" ]; then
cat > "$LIB_NAME/Definitions.lean" << 'EOF'
-- Import only proof tactics (ring, omega, linarith, norm_num, simp, decide, etc.)
-- This is ~1-2GB cache instead of 5GB for `import Mathlib`.
-- Add specific Mathlib imports below as the resource finder identifies them.
-- Example: import Mathlib.Data.Nat.Basic
--          import Mathlib.Combinatorics.SimpleGraph.Basic
import Mathlib.Tactic

namespace LeanProofs

/-!
## Definitions and Notation

Add all definitions, structures, and notation used by the research here.
Import this file from Lemmas.lean and MainTheorem.lean.

To use a specific Mathlib lemma (e.g. Nat.add_comm), add its module here:
  import Mathlib.Data.Nat.Basic
-/

end LeanProofs
EOF
fi

if [ ! -f "$LIB_NAME/Lemmas.lean" ]; then
cat > "$LIB_NAME/Lemmas.lean" << 'EOF'
import LeanProofs.Definitions

namespace LeanProofs

/-!
## Supporting Lemmas

Prove intermediate results here. Each lemma should:
1. Have a doc comment explaining what it says
2. State all hypotheses explicitly
3. End with QED (i.e. no `sorry`)
-/

end LeanProofs
EOF
fi

if [ ! -f "$LIB_NAME/MainTheorem.lean" ]; then
cat > "$LIB_NAME/MainTheorem.lean" << 'EOF'
import LeanProofs.Lemmas

namespace LeanProofs

/-!
## Main Results

State and prove the principal theorems of the research.
-/

end LeanProofs
EOF
fi

# Root import file
cat > "${LIB_NAME}.lean" << EOF
import ${LIB_NAME}.Definitions
import ${LIB_NAME}.Lemmas
import ${LIB_NAME}.MainTheorem
EOF

# ── 5. Get Mathlib cache ──────────────────────────────────────────────────────
# When running inside the neurico-lean Docker image, ~/.cache/mathlib4/ is
# pre-populated at build time.  `lake exe cache get` reads from that local
# cache instead of downloading — making this step instant.
# Outside the image (bare machine), it downloads ~1-2GB from the Mathlib CDN.
echo ""
CACHE_DIR="${HOME}/.cache/mathlib4"
if [ -d "${CACHE_DIR}" ] && [ "$(ls -A "${CACHE_DIR}" 2>/dev/null)" ]; then
  echo "► Mathlib cache found at ${CACHE_DIR} — copying locally (fast)..."
else
  echo "► Mathlib cache not found — downloading (~1-2GB, takes a few minutes)..."
fi
if lake exe cache get; then
  echo "  Mathlib cache ready."
else
  echo "  Cache step failed — will compile from source on first build."
  echo "  (This can take 30–90 minutes the first time.)"
fi

# ── 6. Initial build to confirm setup ────────────────────────────────────────
echo ""
echo "► Running initial build to verify setup..."
if lake build; then
  echo ""
  echo "========================================"
  echo "  Setup complete!"
  echo "  Project: $(pwd)"
  echo ""
  echo "  File layout:"
  echo "    $LIB_NAME/Definitions.lean  — add definitions here"
  echo "    $LIB_NAME/Lemmas.lean       — add supporting lemmas here"
  echo "    $LIB_NAME/MainTheorem.lean  — add main results here"
  echo ""
  echo "  Verify proofs at any time:"
  echo "    cd $PROJECT_DIR && lake build"
  echo "========================================"
else
  echo ""
  echo "  Build failed — check error output above."
  exit 1
fi
