"""
Lean pipeline smoke test with real LLM feedback.

Bypasses all three pipeline stages except the core Lean proof loop:

  ┌─────────────────────────────────────────────────────────────────┐
  │  FULL PIPELINE          │  THIS TEST                            │
  ├─────────────────────────┼───────────────────────────────────────┤
  │  Stage 1: resource finder│  pre-supplied workspace (stub files)  │
  │  Stage 2: expr runner   │  focused 5-step prompt, 15 min limit  │
  │  Stage 3: paper writer  │  skipped                              │
  └─────────────────────────┴───────────────────────────────────────┘

What is actually tested:
  1. setup_lean_project.sh runs successfully in the workspace
  2. The LLM writes a valid .lean file with a specific theorem
  3. lake build exits 0 (type checker accepts the proof)
  4. grep -r "sorry" finds nothing (proof is complete, not stubbed)
  5. The verification.md deliverable is produced

Runtime:  ~10-15 min (Lean setup + first lake build + a few LLM turns)
Cost:     ~$0.10-0.50 (a handful of Claude turns on a trivial problem)

Not run by default — requires claude CLI and valid credentials.

Run:
    pytest tests/test_lean_llm_smoke.py -v -s

Skip all LLM tests:
    pytest -m "not lean_llm" tests/
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
TEMPLATES  = REPO_ROOT / "templates"


# ── Pytest mark ───────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "lean_llm: LLM smoke test — requires claude CLI + credentials, ~10-15 min"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _claude_available() -> bool:
    return shutil.which("claude") is not None


def _lean_available() -> bool:
    return shutil.which("lean") is not None or shutil.which("elan") is not None


def _build_prompt(work_dir: Path, theorem_name: str, theorem_body: str) -> str:
    """Minimal focused prompt — exercises only the Lean proof loop, nothing else."""
    return f"""\
You are running a Lean 4 proof infrastructure smoke test.
Work directory: {work_dir}

Complete ONLY these steps, in order. Do nothing else.

════════════════════════════════════════════════════════════════
STEP 1 — Lean project setup
════════════════════════════════════════════════════════════════

Run the setup script. It installs elan/lean if absent and creates
lean_proofs/ with Mathlib.Tactic:

    bash .claude/skills/lean-prover/scripts/setup_lean_project.sh

Wait for it to finish (lake build will run at the end of the script).
If it succeeds, proceed. If it fails, write the error to
results/lean_smoke_result.txt and stop.

════════════════════════════════════════════════════════════════
STEP 2 — Write the theorem
════════════════════════════════════════════════════════════════

Write EXACTLY this content to lean_proofs/LeanProofs/MainTheorem.lean
(overwrite the starter file):

import LeanProofs.Lemmas

namespace LeanProofs

{theorem_body}

end LeanProofs

════════════════════════════════════════════════════════════════
STEP 3 — Verify with lake build
════════════════════════════════════════════════════════════════

Run:
    cd lean_proofs && lake build 2>&1 | tail -20; cd ..

Expected: exit code 0.
If non-zero: the proof has a type error. Read the error, fix the .lean
file, and rebuild. Try at most 3 times. Stop after 3 failures.

════════════════════════════════════════════════════════════════
STEP 4 — Confirm no sorry
════════════════════════════════════════════════════════════════

Run:
    grep -r "sorry" lean_proofs/LeanProofs/ \\
      && echo "INCOMPLETE — sorry found" \\
      || echo "PROVED — no sorry"

════════════════════════════════════════════════════════════════
STEP 5 — Write result
════════════════════════════════════════════════════════════════

Create results/lean_smoke_result.txt with:
- theorem name: {theorem_name}
- lake build exit code: <value>
- sorry check: PROVED or INCOMPLETE
- lean version: output of `lean --version`

That is all. Do not run any other commands or create any other files.
"""


# ── Workspace fixture ─────────────────────────────────────────────────────────

@pytest.fixture
def smoke_workspace(tmp_path):
    """
    Pre-created workspace that mimics what the resource finder would produce.
    The experiment runner reads these files before starting; providing stubs
    lets us skip Stage 1 entirely.
    """
    work_dir = tmp_path / "lean_smoke"
    work_dir.mkdir()

    # Directories the runner and agent expect
    for d in ["logs", "results", "papers", "src"]:
        (work_dir / d).mkdir()

    # ── Stub resource finder outputs ─────────────────────────────────────────
    (work_dir / "literature_review.md").write_text("""\
# Literature Review (smoke test stub)

## Research Area Overview
Testing Lean 4 proof infrastructure for basic natural number arithmetic.

## Key Definitions
- ℕ: the natural numbers
- Addition on ℕ is commutative

## Mathlib Lemma Catalog
| Informal Result      | Mathlib Name   | Verified? |
|----------------------|----------------|-----------|
| n + m = m + n        | Nat.add_comm   | ✓         |

## Recommendations for Proof Strategy
- Use `ring` tactic for arithmetic equalities (requires Mathlib.Tactic)
- Alternatively: `Nat.add_comm n m` as an exact term proof
""")

    (work_dir / "resources.md").write_text("""\
# Resources (smoke test stub)

## Mathlib Prerequisites
| Result          | Mathlib Name | Used For          |
|-----------------|--------------|-------------------|
| Commutativity + | Nat.add_comm | Main theorem proof |

## Recommendations for Proof Construction
1. Proof strategy: direct proof using ring tactic
2. Mathlib lemmas to cite: Nat.add_comm
3. Lemmas to prove from scratch: none
""")

    # ── Copy lean-prover skill (setup_lean_project.sh lives here) ────────────
    skills_src = TEMPLATES / "skills"
    skills_dst = work_dir / ".claude" / "skills"
    skills_dst.mkdir(parents=True)
    for skill_dir in skills_src.iterdir():
        if skill_dir.is_dir():
            shutil.copytree(skill_dir, skills_dst / skill_dir.name)

    return work_dir


# ── Main smoke test ───────────────────────────────────────────────────────────

@pytest.mark.lean_llm
class TestLeanLLMSmoke:

    THEOREM_NAME = "add_comm_smoke"
    THEOREM_BODY = (
        "/-- Commutativity of addition on ℕ — proved by ring tactic. -/\n"
        "theorem add_comm_smoke (a b : ℕ) : a + b = b + a := by ring"
    )
    TIMEOUT = 900  # 15 minutes

    @pytest.fixture(autouse=True)
    def require_claude(self):
        if not _claude_available():
            pytest.skip("claude CLI not found on PATH")

    def _run_agent(self, work_dir: Path, prompt: str) -> subprocess.CompletedProcess:
        """Launch claude -p with the smoke prompt, stream output."""
        cmd = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--verbose",
            "--output-format", "stream-json",
        ]

        log_file = work_dir / "logs" / "lean_smoke.log"
        start = time.time()

        with open(log_file, "w") as log_f:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(work_dir),
            )
            proc.stdin.write(prompt)
            proc.stdin.close()

            for line in iter(proc.stdout.readline, ""):
                if line:
                    print(line, end="", flush=True)
                    log_f.write(line)

            try:
                return_code = proc.wait(timeout=self.TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                elapsed = time.time() - start
                pytest.fail(
                    f"Agent timed out after {elapsed:.0f}s "
                    f"(limit: {self.TIMEOUT}s).\n"
                    f"Log: {log_file}"
                )

        elapsed = time.time() - start
        print(f"\n⏱  Agent finished in {elapsed:.0f}s (return code {return_code})")
        return subprocess.CompletedProcess(cmd, return_code)

    # ── Test 1: lean project setup ────────────────────────────────────────────

    def test_lean_project_created(self, smoke_workspace):
        """After the smoke run, lean_proofs/ must exist with the full structure."""
        prompt = _build_prompt(smoke_workspace, self.THEOREM_NAME, self.THEOREM_BODY)
        self._run_agent(smoke_workspace, prompt)

        lean_proofs = smoke_workspace / "lean_proofs"
        assert lean_proofs.exists(), (
            "lean_proofs/ was not created — setup_lean_project.sh may have failed.\n"
            f"Logs: {smoke_workspace / 'logs' / 'lean_smoke.log'}"
        )
        assert (lean_proofs / "lakefile.lean").exists(), "lakefile.lean missing"
        assert (lean_proofs / "lean-toolchain").exists(), "lean-toolchain missing"
        assert (lean_proofs / "LeanProofs").is_dir(), "LeanProofs/ directory missing"

    # ── Test 2: theorem was written ───────────────────────────────────────────

    def test_theorem_written_to_main_file(self, smoke_workspace):
        """The agent must have written the theorem to MainTheorem.lean."""
        prompt = _build_prompt(smoke_workspace, self.THEOREM_NAME, self.THEOREM_BODY)
        self._run_agent(smoke_workspace, prompt)

        main_theorem = smoke_workspace / "lean_proofs" / "LeanProofs" / "MainTheorem.lean"
        assert main_theorem.exists(), "MainTheorem.lean not found"

        content = main_theorem.read_text()
        assert self.THEOREM_NAME in content, (
            f"Theorem '{self.THEOREM_NAME}' not found in MainTheorem.lean.\n"
            f"File content:\n{content}"
        )

    # ── Test 3: lake build passes ─────────────────────────────────────────────

    def test_lake_build_exits_zero(self, smoke_workspace):
        """After the agent run, independently verify lake build exits 0."""
        prompt = _build_prompt(smoke_workspace, self.THEOREM_NAME, self.THEOREM_BODY)
        self._run_agent(smoke_workspace, prompt)

        lean_proofs = smoke_workspace / "lean_proofs"
        if not lean_proofs.exists():
            pytest.skip("lean_proofs/ not created — cannot verify lake build")

        result = subprocess.run(
            ["lake", "build"],
            cwd=lean_proofs,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"lake build failed after agent run (exit {result.returncode}).\n"
            f"stdout: {result.stdout[-1000:]}\n"
            f"stderr: {result.stderr[-1000:]}"
        )

    # ── Test 4: no sorry in final state ──────────────────────────────────────

    def test_no_sorry_in_lean_files(self, smoke_workspace):
        """The proof must be complete — no sorry placeholders remaining."""
        prompt = _build_prompt(smoke_workspace, self.THEOREM_NAME, self.THEOREM_BODY)
        self._run_agent(smoke_workspace, prompt)

        lean_dir = smoke_workspace / "lean_proofs" / "LeanProofs"
        if not lean_dir.exists():
            pytest.skip("LeanProofs/ not created — cannot grep for sorry")

        result = subprocess.run(
            ["grep", "-r", "sorry", str(lean_dir)],
            capture_output=True,
            text=True,
        )
        # grep exits non-zero when nothing is found — that is what we want
        assert result.returncode != 0, (
            f"sorry found in lean files — proof is incomplete.\n"
            f"Matches:\n{result.stdout}"
        )

    # ── Test 5: verification.md was produced ──────────────────────────────────

    def test_verification_result_written(self, smoke_workspace):
        """The agent must write results/lean_smoke_result.txt as instructed."""
        prompt = _build_prompt(smoke_workspace, self.THEOREM_NAME, self.THEOREM_BODY)
        self._run_agent(smoke_workspace, prompt)

        result_file = smoke_workspace / "results" / "lean_smoke_result.txt"
        assert result_file.exists(), (
            "results/lean_smoke_result.txt not found — agent may not have "
            "completed all steps.\n"
            f"Logs: {smoke_workspace / 'logs' / 'lean_smoke.log'}"
        )
        content = result_file.read_text()
        # Must contain the theorem name and a verdict
        assert self.THEOREM_NAME in content or "PROVED" in content or "lake" in content, (
            f"Result file exists but content looks wrong:\n{content}"
        )


# ── Consolidated run (one agent call, all assertions) ─────────────────────────

@pytest.mark.lean_llm
class TestLeanLLMSmokeConsolidated:
    """
    Single-agent-call variant: runs the agent ONCE and checks all assertions.
    Use this to avoid 5 separate agent invocations if running the full class above.

    Run:
        pytest tests/test_lean_llm_smoke.py::TestLeanLLMSmokeConsolidated -v -s
    """

    THEOREM_NAME = "add_comm_smoke"
    THEOREM_BODY = (
        "/-- Commutativity of addition on ℕ — proved by ring tactic. -/\n"
        "theorem add_comm_smoke (a b : ℕ) : a + b = b + a := by ring"
    )
    TIMEOUT = 900

    @pytest.fixture(autouse=True)
    def require_claude(self):
        if not _claude_available():
            pytest.skip("claude CLI not found on PATH")

    @pytest.fixture(scope="class")
    def completed_workspace(self, tmp_path_factory):
        """Runs the agent ONCE; all tests in this class share the result."""
        # Check here too — scope="class" runs before autouse method fixtures
        if not _claude_available():
            pytest.skip("claude CLI not found on PATH")

        work_dir = tmp_path_factory.mktemp("lean_smoke_consolidated")
        for d in ["logs", "results", "papers", "src"]:
            (work_dir / d).mkdir()

        # Stub resource finder files
        (work_dir / "literature_review.md").write_text(
            "# Stub\n\n## Mathlib Lemma Catalog\n"
            "| n+m=m+n | Nat.add_comm | ✓ |\n"
        )
        (work_dir / "resources.md").write_text(
            "# Stub\n\n## Mathlib Prerequisites\n"
            "| Commutativity | Nat.add_comm | main proof |\n"
        )

        skills_src = TEMPLATES / "skills"
        skills_dst = work_dir / ".claude" / "skills"
        skills_dst.mkdir(parents=True)
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                shutil.copytree(skill_dir, skills_dst / skill_dir.name)

        # Run agent once
        prompt = _build_prompt(work_dir, self.THEOREM_NAME, self.THEOREM_BODY)
        cmd = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--verbose", "--output-format", "stream-json",
        ]
        log = work_dir / "logs" / "lean_smoke.log"
        with open(log, "w") as log_f:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, cwd=str(work_dir),
            )
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in iter(proc.stdout.readline, ""):
                if line:
                    print(line, end="", flush=True)
                    log_f.write(line)
            try:
                proc.wait(timeout=self.TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                pytest.fail(f"Agent timed out. Log: {log}")

        return work_dir

    def test_lean_project_structure(self, completed_workspace):
        lp = completed_workspace / "lean_proofs"
        assert lp.exists(), "lean_proofs/ not created"
        assert (lp / "lakefile.lean").exists()
        assert (lp / "lean-toolchain").exists()
        assert (lp / "LeanProofs").is_dir()

    def test_theorem_in_main_file(self, completed_workspace):
        f = completed_workspace / "lean_proofs" / "LeanProofs" / "MainTheorem.lean"
        assert f.exists(), "MainTheorem.lean not found"
        assert self.THEOREM_NAME in f.read_text()

    def test_lake_build_passes(self, completed_workspace):
        lp = completed_workspace / "lean_proofs"
        if not lp.exists():
            pytest.skip("lean_proofs/ absent")
        r = subprocess.run(["lake", "build"], cwd=lp,
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, (
            f"lake build failed\nstdout:{r.stdout[-500:]}\nstderr:{r.stderr[-500:]}"
        )

    def test_no_sorry_remaining(self, completed_workspace):
        lean_dir = completed_workspace / "lean_proofs" / "LeanProofs"
        if not lean_dir.exists():
            pytest.skip("LeanProofs/ absent")
        r = subprocess.run(["grep", "-r", "sorry", str(lean_dir)],
                           capture_output=True, text=True)
        assert r.returncode != 0, f"sorry found:\n{r.stdout}"

    def test_result_file_written(self, completed_workspace):
        f = completed_workspace / "results" / "lean_smoke_result.txt"
        assert f.exists(), "lean_smoke_result.txt not written"
        content = f.read_text()
        assert len(content) > 20, f"Result file is too short:\n{content}"
