---
name: axiom-lean-prover
description: Formally verify Lean 4 proofs against Mathlib using the hosted Axiom AXLE API — no local Lean toolchain. Use in the mathematics_lean domain, when a proof needs machine-checked verification but installing Lean/Mathlib locally is undesirable, or when translating informal proofs into formally verified Lean 4 code checked in the cloud.
---

# Axiom Lean Prover (AXLE)

Formal proof verification with Lean 4 + Mathlib, checked by the **hosted Axiom AXLE
API** (https://axle.axiommath.ai). There is **no local Lean install, no `lake`, and
no Mathlib cache** — `.lean` files are sent as text to AXLE, which checks them against
a preloaded full Mathlib and returns structured errors/warnings with source positions.

This is the cloud-verified counterpart of the `lean-prover` skill. If you want a local
`lake build` workflow instead, use `lean-prover`. **Do not mix them in one workspace.**

## When to Use

- Working in the `mathematics_lean` research domain
- Verifying proofs without provisioning a multi-GB local Lean/Mathlib toolchain
- Translating an informal proof into formally verified Lean 4 code
- Checking whether a mathematical statement is provable / type-checks

## Setup

Almost none. You need:

1. `AXLE_API_KEY` in the environment (already passed through from the project `.env`).
   Verify with: `echo "${AXLE_API_KEY:0:6}..."` (should print `pk_...`).
2. Python 3.10+ (already present). The verifier uses only the standard library.

Create a directory for your proof files (any name; `proofs/` by convention):

```bash
mkdir -p proofs
```

That's it — no `elan`, no `lake`, no `lake exe cache get`, no initial build.

## The Verifier: `axle_check.py`

`lake build` is replaced by this one script (the **ground truth** for this domain):

```bash
python .claude/skills/axiom-lean-prover/scripts/axle_check.py proofs/MyProof.lean
```

| Invocation | Meaning |
|---|---|
| `axle_check.py FILE.lean [FILE2 ...]` | Check files, concatenated in the given order |
| `axle_check.py --dir proofs/` | Check every `.lean` under a directory (auto-ordered: Definitions → Lemmas → Theorems) |
| `axle_check.py --code "theorem t : 1=1 := rfl"` | Check an inline snippet (great for `#check`-style lemma lookups) |
| `cat f.lean \| axle_check.py -` | Read from stdin |
| `... --statement-check` | Treat `sorry` as success — for confirming a *stub* type-checks |
| `... --json` | Also dump the raw API response |
| `... --environment lean-4.29.0` | Pin a Lean environment (default `lean-4.29.0`, or `$AXLE_ENV`) |

### Exit codes (use them in loops)

| Code | Status | Meaning |
|---|---|---|
| `0` | `COMPLETE` | Compiles, **no errors, no `sorry`** → the proof is formally done ✓ |
| `2` | `INCOMPLETE_SORRY` | Compiles, but a declaration `uses 'sorry'` → statement OK, proof unfinished |
| `1` | `ERROR` | Compile / type / tactic error → read the messages and fix |
| `3` | `TRANSPORT_ERROR` | Network / auth / quota / usage error (e.g. missing `AXLE_API_KEY`) |

> **A `sorry` proof returns `okay:true` from the API** — it *compiles* but is **not proven**.
> The script catches this and reports `INCOMPLETE_SORRY`. Never report a `sorry`'d result
> as complete. This is the exact analogue of the old "green build but grep finds `sorry`".

### Error positions

On any non-trivial result the script writes the exact text it sent to AXLE to
`.axle_last_check.lean` in the current directory. Lean positions look like
`-:7:12-7:18` (`line:col`); they refer to **that normalized file**, so open it to see
the offending line. (Line numbers differ from your source files because all `import`
lines are collapsed into a single `import Mathlib` at the top — see Imports below.)

## Imports — IMPORTANT (different from the local `lean-prover` skill)

Always start a proof file with the **full** import:

```lean
import Mathlib
```

- The AXLE environment has **all of Mathlib preloaded**; the full import costs nothing
  (it is checked remotely — there is no local cache to download or build).
- The default AXLE environment's import set is exactly `[Mathlib]`. Sending
  `import Mathlib.Tactic` or specific submodules triggers an "Imports mismatch".
- `axle_check.py` strips every `import` line you write and prepends a single
  `import Mathlib` (and sets `ignore_imports`), so submodule imports or **local
  cross-file imports** (`import Proofs.Definitions`) are normalized away and never
  break the check. You still write `import Mathlib` at the top of each file for
  clean, human-readable Lean source.

This is the **opposite** of the `lean-prover` skill's "never use bare `import Mathlib`"
rule — that rule exists only to limit *local* cache size, which is irrelevant here.

## Using lemmas that are NOT in Mathlib

Only **Mathlib** is available remotely — you **cannot `import` an external Lean package**
(an `import SomeProject.Lemmas` line is stripped and its names become `unknown identifier`).
When the resource finder surfaces a lemma that lives outside Mathlib (a paper's companion
formalization, a GitHub Lean project, or an informal result from the literature), you have
two honest options:

### Option 1 (preferred) — inline and prove it
Copy the lemma's **statement and Lean proof** into your `proofs/` files and let AXLE verify
it against Mathlib like any other declaration. If its proof only depends on Mathlib, this is
clean and gives a fully machine-checked result. Re-prove informal (paper) lemmas the same way.

### Option 2 (escape hatch) — cite it as a named `axiom`
If proving a prerequisite would itself require proving a long chain of further non-Mathlib
lemmas (too costly for the session), you may **assume it** rather than re-prove it — but do
this with a named `axiom`, **never with `sorry`**:

```lean
/-- Assumed without proof; established in [Smith 2020, Theorem 3]. -/
axiom key_prerequisite (G : Type*) [Group G] : SomeProperty G
```

Then use `key_prerequisite` freely in downstream proofs. They will verify as
**`COMPLETE (CONDITIONAL on N assumed axiom(s))`** — i.e. correct *modulo* the cited
assumption. `axle_check.py` detects every `axiom` you declare and lists it, so a conditional
result is never mistaken for a fully-closed one.

### `axiom` vs `sorry` — they mean different things

| | Meaning | Verifier status | Use when |
|---|---|---|---|
| `axiom L : …` | Deliberately **assumed**, justified by a citation | `COMPLETE (CONDITIONAL …)`, exit 0 | You are intentionally citing an external result and proceeding |
| `… := by sorry` | **Unfinished** — a proof you still intend to write | `INCOMPLETE_SORRY`, exit 2 | A placeholder during development |

Never use `sorry` as a stand-in for a citation: `sorry` says "not done yet", a named
`axiom` says "assumed on purpose, here's the reference".

### Audit what a result depends on

Lean tracks axiom dependence transitively. Confirm exactly which assumptions a theorem rests
on with `#print axioms`:

```bash
python .claude/skills/axiom-lean-prover/scripts/axle_check.py --code '#print axioms my_main_theorem' --json
# reads back e.g.  'my_main_theorem' depends on axioms: [key_prerequisite, propext, Classical.choice, …]
```

`propext`, `Classical.choice`, `Quot.sound` are Mathlib's standard trusted axioms (expected —
ignore them). Any of **your own** `axiom` names appearing there are cited assumptions that
**must be listed in REPORT.md's Verification Status**, so the result is honestly reported as
"verified modulo {…}".

## Project Structure (convention)

```
proofs/
├── Definitions.lean   # types, structures, notation
├── Lemmas.lean        # supporting lemmas
└── MainTheorem.lean   # main results
```

`axle_check.py --dir proofs/` checks them together in dependency order. Because files
are concatenated, **use one namespace and close it**, or keep everything in a single
file — repeated `namespace Foo ... end Foo` blocks across files are fine, but an
*unclosed* namespace will nest into the next file (a harmless linter warning).
For multi-file proofs, write each file's local `import Proofs.X` as usual; the verifier
strips them and concatenation supplies the actual definitions.

## Verification Workflow (Per Proof)

```bash
# Step 1 — write the statement with `sorry`, confirm it type-checks
python .claude/skills/axiom-lean-prover/scripts/axle_check.py proofs/MainTheorem.lean --statement-check
#   exit 0 → statement is well-typed; proceed to prove it
#   exit 1 → fix the statement (read the error) before attempting the proof

# Step 2 — replace `sorry` with tactics, re-check
python .claude/skills/axiom-lean-prover/scripts/axle_check.py proofs/MainTheorem.lean
#   exit 0 → COMPLETE ✓
#   exit 2 → still has sorry
#   exit 1 → tactic/type error; read the message and adjust

# Step 3 — final whole-project check
python .claude/skills/axiom-lean-prover/scripts/axle_check.py --dir proofs/
#   exit 0 with STATUS: COMPLETE → all proofs formally verified
```

## Looking up Mathlib lemmas without a local Lean

`#check` works through the API — submit it as a snippet:

```bash
python .claude/skills/axiom-lean-prover/scripts/axle_check.py --code '#check @Nat.add_comm'
#   COMPLETE → the name exists; the #check output appears in --json `lean_messages.infos`
#   ERROR "unknown identifier" → it does not exist (wrong name)
```

Add `--json` to read the `#check` type from `lean_messages.infos`. Combine several
`#check` lines in one snippet to probe many names in a single request.

## Writing Proofs

### Theorem / Lemma syntax

```lean
import Mathlib

namespace Proofs

-- Statement only (use sorry to check the type compiles first)
theorem my_theorem (n : ℕ) (h : n > 0) : n * 2 > n := by
  sorry

-- Full proof
theorem my_theorem (n : ℕ) (h : n > 0) : n * 2 > n := by
  omega

end Proofs
```

### Definitions

```lean
def MySet := Finset ℕ

structure MyGraph where
  vertices : Finset ℕ
  edges    : Finset (ℕ × ℕ)

inductive Tree (α : Type) where
  | leaf : Tree α
  | node : α → Tree α → Tree α → Tree α
```

## Core Tactic Reference

| Tactic | When to use |
|--------|-------------|
| `ring` | Equalities in commutative (semi)rings: `a*(b+c) = a*b + a*c` |
| `ring_nf` | Normalize ring expressions without closing the goal |
| `norm_num` | Concrete numerical facts: `2 + 2 = 4`, `Nat.Prime 7` |
| `omega` | Linear arithmetic over `ℤ`/`ℕ`: `n + 1 > n` |
| `linarith` | Linear arithmetic with hypotheses: `h1 : a < b, h2 : b < c ⊢ a < c` |
| `nlinarith` | Nonlinear arithmetic (products of hypotheses) |
| `simp` | Simplify with the simp set; `simp [l1, l2]` to add lemmas |
| `simp only [h]` | Targeted rewrite using only `h`; safer than bare `simp` |
| `exact h` | Close goal exactly with `h` or a term |
| `apply f` | Apply function/lemma `f`, unifying conclusion with goal |
| `rw [h]` / `rw [← h]` | Rewrite left-to-right / right-to-left using equation `h` |
| `constructor` | Split an `And` / `Iff` goal |
| `intro h` | Introduce hypothesis from `∀` or `→` |
| `obtain ⟨a, b, h⟩ := hx` | Destructure existential / conjunction |
| `use x` | Provide a witness for `∃` |
| `cases h` / `rcases` | Case split on inductive type or `Or` |
| `induction n with` | Structural induction |
| `by_contra h` | Proof by contradiction |
| `push_neg` | Push negation inward |
| `contrapose!` | Switch to contrapositive and push negation |
| `gcongr` | Congruence for monotone operations |
| `field_simp` | Clear denominators in field goals |
| `positivity` | Prove `0 < x` or `0 ≤ x` |
| `decide` / `native_decide` | Close decidable props by computation (small / larger finite cases) |
| `tauto` | Propositional tautologies |
| `aesop` | Automated search combining many strategies |

> **Note:** interactive tactics `exact?`, `apply?`, `simp?` are not useful through the
> API (they need an editor). Use `#check` snippets and Mathlib naming conventions instead.

## Searching Mathlib

### Naming conventions (predict lemma names)
- `Nat.add_comm` — commutativity of `+` on `ℕ`
- `Int.mul_neg` — negation rule for `*` on `ℤ`
- `List.map_comp` — `map` composed with `comp`
- Type-namespaced: `Finset.`, `Set.`, `Matrix.`, `Polynomial.`

### `#check` to confirm a name exists (via the API, see above)
### Web search
`leanprover-community.github.io/mathlib4_docs` for the exact namespace.

## Interpreting Lean Error Messages

(Identical to local Lean — same kernel, same Mathlib. These appear in
`lean_messages.errors` with a `-:line:col` position.)

| Error | Meaning |
|-------|---------|
| `unknown identifier 'foo'` | `foo` not in scope — usually a wrong Mathlib name; check with `#check` |
| `type mismatch: expected X got Y` | Wrong type — check the hypothesis you're applying |
| `unsolved goals: ⊢ P` | Proof incomplete — `P` still needs proving |
| `application type mismatch` | Applied a lemma to the wrong argument type |
| `failed to synthesize instance` | Missing typeclass — may need `[DecidableEq α]` etc. |
| `declaration uses 'sorry'` | Type-checks but NOT proven — replace every `sorry` (reported as `INCOMPLETE_SORRY`) |
| `Imports mismatch` | You sent non-`Mathlib` imports without normalization — let `axle_check.py` handle imports |

## Proof Skeleton Template

```lean
import Mathlib

namespace Proofs

/-- One-line description of what this proves. -/
theorem theorem_name
    (param1 : Type1) (param2 : Type2)
    (hyp1 : Condition1) (hyp2 : Condition2) :
    Conclusion := by
  sorry  -- replace with the actual proof

/-- Supporting lemma used in the main theorem. -/
lemma lemma_name (n : ℕ) : n + 0 = n := by
  simp

end Proofs
```

## Tips

- **State first, prove later.** Stub every statement with `sorry`, run with
  `--statement-check` until all type-check, then fill in proofs bottom-up.
- **Automation first.** Try `omega`, `simp`, `ring`, `norm_num`, `linarith`, `aesop`
  before hand-writing tactic steps.
- **Mind rate limits.** AXLE allows ~20 concurrent requests per key. The check is fast
  (~50–100 ms), but check *meaningful units* (a full file) rather than spamming
  one-line edits.
- **Pin the environment** with `--environment` (or `$AXLE_ENV`) and record it in your
  report for reproducibility — it determines the Lean and Mathlib versions used.
