---
name: lean-prover
description: Formally verify mathematical proofs using Lean 4 and Mathlib. Use when working in the mathematics_lean domain, when a proof needs machine-checked verification, or when translating informal proofs into formally verified Lean 4 code.
---

# Lean Prover

Formal proof verification using Lean 4 and the Mathlib mathematics library.

## When to Use

- Working in the `mathematics_lean` research domain
- Translating an informal proof into formally verified code
- Checking whether a mathematical statement is provable
- Searching Mathlib for existing lemmas to cite or reuse

## Project Setup

Run the setup script from your workspace root:

```bash
bash .claude/skills/lean-prover/scripts/setup_lean_project.sh
```

This creates `lean_proofs/` with Mathlib as a dependency and downloads the
prebuilt cache. After setup, all proof work lives inside `lean_proofs/`.

**Manual setup (if the script fails):**

```bash
# 1. Install elan (Lean version manager) if not present
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  | sh -s -- -y
source "$HOME/.elan/env"

# 2. Create a Mathlib project
mkdir lean_proofs && cd lean_proofs
lake +leanprover-community/mathlib4:stable init lean_proofs math
# ↑ "math" template wires up Mathlib automatically

# 3. Download prebuilt Mathlib cache (avoids a multi-hour source build)
lake exe cache get

# 4. Verify setup
lake build
cd ..
```

## Project Structure

```
lean_proofs/
├── lakefile.lean          # Build config — Mathlib dependency lives here
├── lean-toolchain         # Pinned Lean version (must match Mathlib)
└── LeanProofs/
    ├── Definitions.lean   # All definitions and notation
    ├── Lemmas.lean        # Supporting lemmas (import Definitions)
    └── MainTheorem.lean   # Main results (import Lemmas)
```

Root import file (`LeanProofs.lean`):
```lean
import LeanProofs.Definitions
import LeanProofs.Lemmas
import LeanProofs.MainTheorem
```

## Writing Proofs

### File header

Every `.lean` file should start with:
```lean
import Mathlib
import LeanProofs.Definitions  -- if referencing other local files

namespace LeanProofs
-- ... your content ...
end LeanProofs
```

### Theorem / Lemma syntax

```lean
-- Statement only (use sorry to check the type compiles first)
theorem my_theorem (n : ℕ) (h : n > 0) : n * 2 > n := by
  sorry

-- Full proof
theorem my_theorem (n : ℕ) (h : n > 0) : n * 2 > n := by
  linarith
```

### Definitions

```lean
-- Type alias
def MySet := Finset ℕ

-- Structure
structure MyGraph where
  vertices : Finset ℕ
  edges    : Finset (ℕ × ℕ)

-- Inductive type
inductive Tree (α : Type) where
  | leaf : Tree α
  | node : α → Tree α → Tree α → Tree α
```

## Core Tactic Reference

| Tactic | When to use |
|--------|-------------|
| `ring` | Prove equalities in commutative (semi)rings: `a*(b+c) = a*b + a*c` |
| `ring_nf` | Normalize ring expressions without closing the goal |
| `norm_num` | Prove concrete numerical facts: `2 + 2 = 4`, `7.isPrime` |
| `omega` | Linear arithmetic over `ℤ` and `ℕ`: `n + 1 > n` |
| `linarith` | Linear arithmetic with hypotheses: `h1 : a < b, h2 : b < c ⊢ a < c` |
| `nlinarith` | Nonlinear arithmetic (products of hypotheses) |
| `simp` | Simplify using the simp lemma set; use `simp [lemma1, lemma2]` to add |
| `simp only [h]` | Targeted rewrite using only `h`; safer than bare `simp` |
| `exact h` | Close goal exactly with hypothesis `h` or a term |
| `apply f` | Apply function/lemma `f`, unifying conclusion with goal |
| `rw [h]` | Rewrite goal left-to-right using equation `h` |
| `rw [← h]` | Rewrite right-to-left |
| `constructor` | Split an `And` goal or `Iff` into two subgoals |
| `intro h` | Introduce hypothesis from `∀` or `→` |
| `obtain ⟨a, b, h⟩ := hx` | Destructure existential or And hypothesis |
| `use x` | Provide witness for `∃` goal |
| `cases h` | Case split on inductive type or `Or` |
| `induction n with` | Structural induction |
| `by_contra h` | Proof by contradiction |
| `push_neg` | Push negation inward: `¬ ∀ x, P x` → `∃ x, ¬ P x` |
| `contrapose!` | Switch to contrapositive and push negation |
| `gcongr` | Congruence for monotone operations |
| `field_simp` | Clear denominators in field goals |
| `positivity` | Prove `0 < x` or `0 ≤ x` goals |
| `decide` | Close decidable propositions by computation (small finite cases) |
| `native_decide` | Like `decide` but compiled — handles larger cases |
| `tauto` | Propositional tautologies |
| `aesop` | Automated search combining many strategies |
| `exact?` | **(Interactive only)** Search for a term matching the goal |
| `apply?` | **(Interactive only)** Search for applicable lemmas |
| `simp?` | **(Interactive only)** Show which simp lemmas closed/simplified the goal |

## Searching Mathlib

Since `exact?` / `apply?` are interactive-only, use these strategies in batch mode:

### 1. `#check` — verify a name exists
```lean
#check Nat.add_comm      -- Nat.add_comm : ∀ (n m : ℕ), n + m = m + n
#check List.length_map   -- look up list lemmas
```

### 2. Naming conventions (predict lemma names)
Mathlib names follow a consistent pattern:
- `Nat.add_comm`  — commutativity of `+` on `ℕ`
- `Int.mul_neg`   — negation rule for `*` on `ℤ`
- `List.map_comp` — `map` composed with `comp`
- Prefix with type namespace: `Finset.`, `Set.`, `Matrix.`, `Polynomial.`

### 3. `Mathlib.Tactic.Polyrith` / `polyrith`
For polynomial arithmetic identities that `ring` can't close automatically.

### 4. Web search
Search `leanprover-community.github.io/mathlib4_docs` for the exact namespace.
Example: search "Nat prime" to find `Nat.Prime`, `Nat.Prime.two_le`, etc.

## Verification Workflow (Per Proof)

```bash
# Step 1 — stub the statement, check it type-checks
# Add `sorry` as the proof body

# Step 2 — build to confirm the statement compiles
cd lean_proofs && lake build 2>&1; cd ..

# Step 3 — replace sorry with tactics, rebuild
# Repeat until exit code is 0 with no "sorry" warnings

# Step 4 — grep to confirm no sorry remains
grep -r "sorry" lean_proofs/LeanProofs/ && echo "INCOMPLETE PROOFS FOUND" || echo "All proofs complete"
```

`lake build` exit code semantics:
- **0** — everything compiled; if no `sorry`, proof is formally complete
- **non-zero** — type error or tactic failure; stderr contains the exact error location and message

## Interpreting Lean Error Messages

| Error | Meaning |
|-------|---------|
| `unknown identifier 'foo'` | `foo` not in scope — check import or namespace |
| `type mismatch: expected X got Y` | Wrong type — check the hypothesis you're applying |
| `unsolved goals: ⊢ P` | Proof is incomplete — `P` still needs to be proved |
| `application type mismatch` | Applied lemma to wrong argument type |
| `failed to synthesize instance` | Missing typeclass — may need `[DecidableEq α]` or similar |
| `declaration uses sorry` | Proof accepted but marked incomplete — replace all `sorry` |

## Proof Skeleton Template

Use this as a starting point for each new result:

```lean
/-- One-line description of what this proves. -/
theorem theorem_name
    (param1 : Type1)
    (param2 : Type2)
    (hyp1 : Condition1)
    (hyp2 : Condition2) :
    Conclusion := by
  sorry  -- replace with actual proof

/-- Supporting lemma used in the main theorem. -/
lemma lemma_name (n : ℕ) : n + 0 = n := by
  ring
```

## Common Mathlib Imports by Area

```lean
-- ALWAYS start with this — gives all tactics, ~1-2GB cache instead of 5GB:
import Mathlib.Tactic

-- Then add only the specific content modules you need:
import Mathlib.Algebra.Group.Basic        -- groups, monoids
import Mathlib.Algebra.Ring.Basic         -- rings
import Mathlib.Algebra.Field.Basic        -- fields
import Mathlib.Data.Nat.Basic             -- ℕ lemmas
import Mathlib.Data.Int.Basic             -- ℤ lemmas
import Mathlib.Data.Real.Basic            -- ℝ lemmas
import Mathlib.Data.Finset.Basic          -- finite sets
import Mathlib.Combinatorics.SimpleGraph.Basic  -- graph theory
import Mathlib.Topology.Basic             -- topology
import Mathlib.Analysis.SpecialFunctions.Pow.Real  -- real powers
import Mathlib.NumberTheory.Primes        -- prime numbers
import Mathlib.LinearAlgebra.Matrix.Basic -- matrices
```

**Avoid `import Mathlib`** — it pulls the full 5GB cache and slower compile times.
Use `import Mathlib.Tactic` as your base and add specific modules as needed.
The resource finder's Mathlib lemma catalog tells you exactly which modules to add.

## References

See `references/` folder for:
- `lean4_cheatsheet.md`: Quick syntax reference
- `mathlib_search_guide.md`: How to find lemmas by name pattern
