"""
Integration tests for the Lean proof feedback loop.

These tests verify the shell-level behaviors that the session_instructions
template prescribes WITHOUT calling the Claude LLM at all — making them
free to run in terms of API cost.

Three tiers, by cost/speed:

  Tier 1  lean_binary   — `lean --stdin` only; instant once lean is installed
  Tier 2  lean_lake     — minimal Lake project (no Mathlib); seconds per test
  Tier 3  lean_mathlib  — full setup_lean_project.sh with Mathlib; slow

Run fast tests only (default):
    pytest tests/test_lean_integration.py -m "not lean_mathlib"

Run everything including Mathlib:
    pytest tests/test_lean_integration.py

Skip all Lean tests (e.g. in CI without lean installed):
    pytest tests/test_lean_integration.py -m "not lean_binary"
"""

import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT    = Path(__file__).parent.parent
SETUP_SCRIPT = REPO_ROOT / "templates" / "skills" / "lean-prover" / "scripts" / "setup_lean_project.sh"

# ── Pytest marks ──────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "lean_binary: requires lean binary on PATH")
    config.addinivalue_line("markers", "lean_lake:   requires lean + lake on PATH")
    config.addinivalue_line("markers", "lean_mathlib: slow — downloads Mathlib cache")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd=None, input_text=None, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _lean_path() -> str | None:
    return shutil.which("lean")


def _lake_path() -> str | None:
    return shutil.which("lake")


def _elan_path() -> str | None:
    return shutil.which("elan")


# ── Session-level availability checks ────────────────────────────────────────

@pytest.fixture(scope="session")
def lean_bin():
    path = _lean_path()
    if path is None:
        pytest.skip(
            "lean binary not found on PATH.\n"
            "Install with: curl -sSfL https://raw.githubusercontent.com/"
            "leanprover/elan/master/elan-init.sh | sh -s -- -y"
        )
    return path


@pytest.fixture(scope="session")
def lake_bin(lean_bin):
    path = _lake_path()
    if path is None:
        pytest.skip("lake binary not found on PATH (usually installed with elan)")
    return path


# ── Tier 1: lean --stdin (no project, no Mathlib) ────────────────────────────

@pytest.mark.lean_binary
class TestLeanBinaryFeedbackLoop:
    """
    Tests the core sorry/valid/error feedback loop using `lean --stdin`.
    No project, no Mathlib, no internet needed.
    Exercises the exact semantics the session_instructions relies on.
    """

    # ── valid proof ───────────────────────────────────────────────────────────

    def test_valid_proof_exits_zero(self, lean_bin):
        """A correct proof must exit 0 — the session_instructions 'proof complete' signal."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t (n : Nat) : n + 0 = n := Nat.add_zero n\n",
        )
        assert result.returncode == 0, (
            f"Valid proof should exit 0.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_valid_proof_produces_no_sorry_warning(self, lean_bin):
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t (n : Nat) : n + 0 = n := Nat.add_zero n\n",
        )
        combined = result.stdout + result.stderr
        assert "sorry" not in combined.lower(), (
            "A proof with no sorry must not produce a 'sorry' warning"
        )

    def test_omega_proves_linear_arithmetic(self, lean_bin):
        """omega is a core tactic (no Mathlib) — must close simple linear goals."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t (n : Nat) : n + 1 > n := by omega\n",
        )
        assert result.returncode == 0, (
            f"omega should close 'n + 1 > n'.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_decide_proves_concrete_fact(self, lean_bin):
        """decide computes decidable propositions — no Mathlib needed."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t : (2 : Nat) + 2 = 4 := by decide\n",
        )
        assert result.returncode == 0, (
            f"decide should close '2 + 2 = 4'.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # ── sorry behavior ────────────────────────────────────────────────────────

    def test_sorry_exits_zero(self, lean_bin):
        """sorry must exit 0 (accepted by Lean) so the loop can continue."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t (n : Nat) : n + 0 = n := by sorry\n",
        )
        assert result.returncode == 0, (
            f"sorry should exit 0.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_sorry_produces_warning(self, lean_bin):
        """sorry must produce a 'declaration uses sorry' warning — the grep target."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t (n : Nat) : n + 0 = n := by sorry\n",
        )
        combined = result.stdout + result.stderr
        assert "sorry" in combined.lower(), (
            "sorry proof must produce a warning containing 'sorry'"
        )

    def test_declaration_uses_sorry_message(self, lean_bin):
        """The specific 'declaration uses sorry' string from the error table in SKILL.md."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t : True := by sorry\n",
        )
        combined = result.stdout + result.stderr
        assert "declaration uses 'sorry'" in combined or "uses sorry" in combined, (
            "The 'declaration uses sorry' message must appear in Lean's output"
        )

    # ── type errors ───────────────────────────────────────────────────────────

    def test_type_error_exits_nonzero(self, lean_bin):
        """A type error must exit non-zero — the agent's signal to fix the proof."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t : (1 : Nat) = 2 := by rfl\n",
        )
        assert result.returncode != 0, (
            f"Type error (1 = 2 by rfl) should exit non-zero.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_type_error_message_in_output(self, lean_bin):
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t : (1 : Nat) = 2 := by rfl\n",
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, "Type error must produce output for the agent to read"

    def test_unknown_identifier_error(self, lean_bin):
        """'unknown identifier' appears when the agent misspells a lemma name."""
        result = _run(
            [lean_bin, "--stdin"],
            input_text="theorem t : True := obviously_true\n",
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "unknown" in combined.lower() or "identifier" in combined.lower(), (
            "Using a non-existent identifier must produce an 'unknown identifier' error"
        )

    def test_unsolved_goals_error(self, lean_bin):
        """'unsolved goals' appears when a tactic doesn't close the proof."""
        result = _run(
            [lean_bin, "--stdin"],
            # intro doesn't close the goal — leaves a goal open
            input_text="theorem t (h : True) : True := by intro\n",
        )
        combined = result.stdout + result.stderr
        # Either unsolved goals or a different error — the point is it fails
        assert result.returncode != 0 or "unsolved" in combined.lower(), (
            "An incomplete tactic proof must fail"
        )


# ── Tier 2: minimal Lake project (no Mathlib, fast) ───────────────────────────

@pytest.fixture(scope="module")
def minimal_lake_workspace(tmp_path_factory, lean_bin, lake_bin):
    """
    Create a minimal Lake project WITHOUT Mathlib.
    This mimics the lean_proofs/ structure the session_instructions prescribes,
    but avoids the Mathlib download so tests run in seconds.
    """
    d = tmp_path_factory.mktemp("lean_minimal")

    # Minimal lakefile — no Mathlib dependency
    (d / "lakefile.lean").write_text(textwrap.dedent("""\
        import Lake
        open Lake DSL

        package «proofs» where
          name := "proofs"

        lean_lib «LeanProofs»
    """))

    # Root import file (matches session_instructions structure)
    (d / "LeanProofs.lean").write_text(textwrap.dedent("""\
        import LeanProofs.Definitions
        import LeanProofs.Lemmas
        import LeanProofs.MainTheorem
    """))

    lib = d / "LeanProofs"
    lib.mkdir()

    # Starter files with the same content the setup script creates,
    # but importing core Lean instead of Mathlib
    (lib / "Definitions.lean").write_text(textwrap.dedent("""\
        namespace LeanProofs

        /-!
        ## Definitions and Notation
        -/

        end LeanProofs
    """))

    (lib / "Lemmas.lean").write_text(textwrap.dedent("""\
        import LeanProofs.Definitions

        namespace LeanProofs

        /-!
        ## Supporting Lemmas
        -/

        end LeanProofs
    """))

    (lib / "MainTheorem.lean").write_text(textwrap.dedent("""\
        import LeanProofs.Lemmas

        namespace LeanProofs

        /-!
        ## Main Results
        -/

        end LeanProofs
    """))

    # Run initial build to ensure the empty project compiles
    result = _run([lake_bin, "build"], cwd=d, timeout=120)
    if result.returncode != 0:
        pytest.skip(
            f"Initial lake build failed (lean toolchain issue?).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    return d


@pytest.mark.lean_lake
class TestLakeBuildFeedbackLoop:
    """
    Tests the exact `cd lean_proofs && lake build 2>&1 ; cd ..` pattern
    prescribed by the session_instructions, using a minimal project.
    """

    def _write_main_theorem(self, workspace: Path, content: str):
        (workspace / "LeanProofs" / "MainTheorem.lean").write_text(
            textwrap.dedent(f"""\
                import LeanProofs.Lemmas

                namespace LeanProofs

                {content}

                end LeanProofs
            """)
        )

    # ── valid proofs ──────────────────────────────────────────────────────────

    def test_valid_core_proof_exits_zero(self, minimal_lake_workspace, lake_bin):
        """A correct proof in MainTheorem.lean must make lake build exit 0."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem add_zero (n : Nat) : n + 0 = n := Nat.add_zero n"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        assert result.returncode == 0, (
            f"Valid proof must make lake build exit 0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_omega_proof_exits_zero(self, minimal_lake_workspace, lake_bin):
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem lt_succ (n : Nat) : n < n + 1 := by omega"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        assert result.returncode == 0, (
            f"omega proof must make lake build exit 0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # ── sorry behavior ────────────────────────────────────────────────────────

    def test_sorry_lake_build_exits_zero(self, minimal_lake_workspace, lake_bin):
        """sorry must exit 0 so the agent can iterate — not block the loop."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem stub (n : Nat) : n + 0 = n := by sorry"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        assert result.returncode == 0, (
            f"sorry proof must make lake build exit 0 (warning, not error).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_sorry_lake_build_produces_warning(self, minimal_lake_workspace, lake_bin):
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem stub (n : Nat) : n + 0 = n := by sorry"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        combined = result.stdout + result.stderr
        assert "sorry" in combined.lower(), (
            "sorry proof must produce a warning in lake build output"
        )

    # ── grep-sorry completion check ───────────────────────────────────────────

    def test_grep_finds_sorry_in_incomplete_proof(self, minimal_lake_workspace):
        """The `grep -r sorry lean_proofs/LeanProofs/` check must find sorry."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem stub (n : Nat) : n + 0 = n := by sorry"
        )
        lean_dir = minimal_lake_workspace / "LeanProofs"
        result = _run(["grep", "-r", "sorry", str(lean_dir)])
        assert result.returncode == 0, (
            "grep must return 0 (found matches) when sorry is present"
        )
        assert "sorry" in result.stdout, (
            "grep output must contain the matched 'sorry' line"
        )

    def test_grep_returns_nonzero_after_sorry_removed(self, minimal_lake_workspace):
        """After replacing sorry with a real proof, grep must return non-zero (no match)."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem stub (n : Nat) : n + 0 = n := Nat.add_zero n"
        )
        lean_dir = minimal_lake_workspace / "LeanProofs"
        result = _run(["grep", "-r", "sorry", str(lean_dir)])
        assert result.returncode != 0, (
            "grep must return non-zero (no matches) when no sorry remains"
        )

    def test_grep_sorry_or_echo_workflow(self, minimal_lake_workspace):
        """The exact pipeline pattern:
            grep -r 'sorry' lean/... && echo INCOMPLETE || echo OK
        Must print OK when proofs are complete.
        """
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem done (n : Nat) : n + 0 = n := Nat.add_zero n"
        )
        lean_dir = minimal_lake_workspace / "LeanProofs"
        result = _run(
            ["bash", "-c",
             f'grep -r "sorry" {lean_dir} && echo "INCOMPLETE PROOFS FOUND" || echo "All proofs complete"'],
        )
        assert "All proofs complete" in result.stdout, (
            f"Workflow should print 'All proofs complete' when no sorry.\n"
            f"stdout: {result.stdout}"
        )

    # ── type error handling ───────────────────────────────────────────────────

    def test_type_error_exits_nonzero(self, minimal_lake_workspace, lake_bin):
        """A type error in a .lean file must make lake build exit non-zero."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem bad : (1 : Nat) = 2 := by rfl"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        assert result.returncode != 0, (
            "Type error must make lake build exit non-zero"
        )

    def test_type_error_produces_output(self, minimal_lake_workspace, lake_bin):
        """The agent reads stderr to understand what to fix."""
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem bad : (1 : Nat) = 2 := by rfl"
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        combined = result.stdout + result.stderr
        assert len(combined) > 0, "Type error must produce diagnostic output"

    # ── file structure expected by session instructions ───────────────────────

    def test_import_chain_compiles(self, minimal_lake_workspace, lake_bin):
        """Definitions ← Lemmas ← MainTheorem import chain must compile clean."""
        (minimal_lake_workspace / "LeanProofs" / "Definitions.lean").write_text(
            textwrap.dedent("""\
                namespace LeanProofs
                def myConst : Nat := 42
                end LeanProofs
            """)
        )
        (minimal_lake_workspace / "LeanProofs" / "Lemmas.lean").write_text(
            textwrap.dedent("""\
                import LeanProofs.Definitions
                namespace LeanProofs
                theorem myConst_pos : myConst > 0 := by unfold myConst; omega
                end LeanProofs
            """)
        )
        (minimal_lake_workspace / "LeanProofs" / "MainTheorem.lean").write_text(
            textwrap.dedent("""\
                import LeanProofs.Lemmas
                namespace LeanProofs
                theorem myConst_nonzero : myConst ≠ 0 := by
                  have := myConst_pos; omega
                end LeanProofs
            """)
        )
        result = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=120)
        assert result.returncode == 0, (
            f"3-file import chain must compile.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_lake_clean_then_build(self, minimal_lake_workspace, lake_bin):
        """The session instructions prescribe `lake clean && lake build` for Phase 4.
        Verify clean + fresh build succeeds.
        """
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem t (n : Nat) : n + 0 = n := Nat.add_zero n"
        )
        clean = _run([lake_bin, "clean"], cwd=minimal_lake_workspace, timeout=30)
        assert clean.returncode == 0, "lake clean should succeed"

        build = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=120)
        assert build.returncode == 0, (
            f"lake build after clean must succeed.\n"
            f"stdout: {build.stdout}\nstderr: {build.stderr}"
        )

    def test_verification_md_content(self, minimal_lake_workspace, lake_bin):
        """The session_instructions prescribes writing results/verification.md with
        the lake build output and grep-sorry result. Verify we can produce that content.
        """
        self._write_main_theorem(
            minimal_lake_workspace,
            "theorem t (n : Nat) : n + 0 = n := Nat.add_zero n"
        )
        build = _run([lake_bin, "build"], cwd=minimal_lake_workspace, timeout=60)
        lean_dir = minimal_lake_workspace / "LeanProofs"
        grep = _run(["grep", "-r", "sorry", str(lean_dir)])

        results_dir = minimal_lake_workspace / "results"
        results_dir.mkdir(exist_ok=True)

        verification_md = results_dir / "verification.md"
        verification_md.write_text(
            f"# Verification\n\n"
            f"## lake build exit code\n{build.returncode}\n\n"
            f"## grep sorry output\n"
            f"{'No sorry found (exit {})'.format(grep.returncode) if grep.returncode != 0 else grep.stdout}\n"
        )

        content = verification_md.read_text()
        assert "lake build exit code" in content
        assert "grep sorry" in content
        assert str(build.returncode) in content


# ── Tier 3: full setup_lean_project.sh with Mathlib (slow) ───────────────────

@pytest.fixture(scope="module")
def mathlib_workspace(tmp_path_factory, lean_bin, lake_bin):
    """
    Run the actual setup_lean_project.sh to create a full Mathlib workspace.
    This is slow (5-30 min on first run) — only used for lean_mathlib tests.
    """
    d = tmp_path_factory.mktemp("lean_mathlib")

    result = _run(
        ["bash", str(SETUP_SCRIPT)],
        cwd=d,
        timeout=3600,  # allow up to 1 hour for Mathlib cache download
    )

    if result.returncode != 0:
        pytest.skip(
            f"setup_lean_project.sh failed (no network? wrong toolchain?).\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )

    lean_proofs = d / "lean_proofs"
    if not lean_proofs.exists():
        pytest.skip("setup_lean_project.sh ran but lean_proofs/ was not created")

    return lean_proofs


@pytest.mark.lean_mathlib
@pytest.mark.slow
class TestMathlibWorkflow:
    """Full Mathlib integration — runs the actual setup script and proves a theorem."""

    def test_project_structure_created(self, mathlib_workspace):
        assert (mathlib_workspace / "lakefile.lean").exists()
        assert (mathlib_workspace / "lean-toolchain").exists()
        assert (mathlib_workspace / "LeanProofs").is_dir()
        assert (mathlib_workspace / "LeanProofs" / "Definitions.lean").exists()
        assert (mathlib_workspace / "LeanProofs" / "Lemmas.lean").exists()
        assert (mathlib_workspace / "LeanProofs" / "MainTheorem.lean").exists()

    def test_initial_build_succeeds(self, mathlib_workspace, lake_bin):
        result = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=600)
        assert result.returncode == 0, (
            f"Initial Mathlib project build must succeed.\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )

    def test_ring_tactic_proves_arithmetic(self, mathlib_workspace, lake_bin):
        """ring is the canonical Mathlib automation tactic mentioned in SKILL.md."""
        (mathlib_workspace / "LeanProofs" / "MainTheorem.lean").write_text(
            textwrap.dedent("""\
                import LeanProofs.Lemmas

                namespace LeanProofs

                -- Simple question: prove n^2 + 2n + 1 = (n+1)^2
                theorem sq_expand (n : ℕ) : n ^ 2 + 2 * n + 1 = (n + 1) ^ 2 := by ring

                end LeanProofs
            """)
        )
        result = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=300)
        assert result.returncode == 0, (
            f"'ring' should prove n² + 2n + 1 = (n+1)².\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )

    def test_norm_num_proves_concrete_fact(self, mathlib_workspace, lake_bin):
        """norm_num is the Mathlib tactic for concrete numerical goals."""
        (mathlib_workspace / "LeanProofs" / "MainTheorem.lean").write_text(
            textwrap.dedent("""\
                import LeanProofs.Lemmas

                namespace LeanProofs

                theorem two_pow_10 : (2 : ℕ) ^ 10 = 1024 := by norm_num

                end LeanProofs
            """)
        )
        result = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=300)
        assert result.returncode == 0, (
            f"norm_num should prove 2^10 = 1024.\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )

    def test_mathlib_lemma_cite_works(self, mathlib_workspace, lake_bin):
        """Citing Nat.add_comm by name (as the resource finder catalogs) must compile."""
        (mathlib_workspace / "LeanProofs" / "MainTheorem.lean").write_text(
            textwrap.dedent("""\
                import LeanProofs.Lemmas

                namespace LeanProofs

                -- Cite a Mathlib lemma by name (as the resource finder catalogs it)
                theorem comm_example (n m : ℕ) : n + m = m + n :=
                  Nat.add_comm n m

                end LeanProofs
            """)
        )
        result = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=300)
        assert result.returncode == 0, (
            f"Nat.add_comm cited by name must compile.\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )

    def test_sorry_and_grep_workflow(self, mathlib_workspace, lake_bin):
        """End-to-end: sorry → lake build exits 0 → grep finds sorry → replace → clean."""
        lean_dir = mathlib_workspace / "LeanProofs"
        main = lean_dir / "MainTheorem.lean"

        # Step 1: write sorry stub
        main.write_text(textwrap.dedent("""\
            import LeanProofs.Lemmas
            namespace LeanProofs
            theorem my_result (n : ℕ) : n ^ 2 + 2 * n + 1 = (n + 1) ^ 2 := by sorry
            end LeanProofs
        """))

        build1 = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=300)
        assert build1.returncode == 0, "sorry stub must exit 0"

        grep1 = _run(["grep", "-r", "sorry", str(lean_dir)])
        assert grep1.returncode == 0, "grep must find sorry in stub"

        # Step 2: replace sorry with real proof
        main.write_text(textwrap.dedent("""\
            import LeanProofs.Lemmas
            namespace LeanProofs
            theorem my_result (n : ℕ) : n ^ 2 + 2 * n + 1 = (n + 1) ^ 2 := by ring
            end LeanProofs
        """))

        build2 = _run([lake_bin, "build"], cwd=mathlib_workspace, timeout=300)
        assert build2.returncode == 0, "completed proof must exit 0"

        grep2 = _run(["grep", "-r", "sorry", str(lean_dir)])
        assert grep2.returncode != 0, "grep must return non-zero when no sorry remains"
