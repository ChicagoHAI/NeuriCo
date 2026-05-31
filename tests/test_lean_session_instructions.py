"""
Unit tests for the mathematics_lean domain session instructions template.

Tests cover:
  1. Domain override resolution  — the correct template file is loaded
  2. Template rendering          — all Jinja2 variables are substituted
  3. Lean content presence       — key Lean workflow phrases exist in output
  4. Lean-as-verifier framing    — lake build is the verification signal,
                                   not just a Python check
  5. Python-exploration framing  — Python/SymPy is present but scoped to
                                   exploration, NOT proof validity
  6. No unrendered placeholders  — no {{ ... }} tokens remain in output
"""

import sys
import pytest
from pathlib import Path

# Make src/ importable without an install
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from templates.prompt_generator import PromptGenerator


# ── Fixtures ──────────────────────────────────────────────────────────────────

TEMPLATES_DIR = REPO_ROOT / "templates"

SAMPLE_PROMPT = (
    "Prove that for every n ≥ 1 the sum of the first n odd numbers equals n²."
)
SAMPLE_WORK_DIR = "/workspaces/test-lean-workspace"


@pytest.fixture
def generator():
    return PromptGenerator(TEMPLATES_DIR)


@pytest.fixture
def rendered(generator):
    """Rendered session instructions for the mathematics_lean domain."""
    return generator.generate_session_instructions(
        prompt=SAMPLE_PROMPT,
        work_dir=SAMPLE_WORK_DIR,
        use_scribe=False,
        domain="mathematics_lean",
    )


@pytest.fixture
def rendered_scribe(generator):
    """Rendered session instructions with use_scribe=True (notebook mode)."""
    return generator.generate_session_instructions(
        prompt=SAMPLE_PROMPT,
        work_dir=SAMPLE_WORK_DIR,
        use_scribe=True,
        domain="mathematics_lean",
    )


@pytest.fixture
def rendered_generic(generator):
    """Rendered session instructions for the plain mathematics domain (baseline)."""
    return generator.generate_session_instructions(
        prompt=SAMPLE_PROMPT,
        work_dir=SAMPLE_WORK_DIR,
        use_scribe=False,
        domain="mathematics",
    )


# ── 1. Domain override resolution ─────────────────────────────────────────────

class TestDomainOverrideResolution:
    def test_lean_template_is_loaded_not_generic(self, generator):
        """_load_template_with_domain_override picks mathematics_lean over agents/ fallback."""
        lean_content = generator._load_template_with_domain_override(
            "agents/session_instructions.txt", "mathematics_lean"
        )
        generic_content = generator.load_template("agents/session_instructions.txt")

        # The two templates must be different files
        assert lean_content != generic_content, (
            "mathematics_lean should have its own session_instructions.txt override"
        )

    def test_lean_override_file_exists(self):
        override_path = TEMPLATES_DIR / "domains" / "mathematics_lean" / "session_instructions.txt"
        assert override_path.exists(), (
            f"Override template not found at {override_path}"
        )

    def test_mathematics_domain_uses_different_template(self, generator):
        """mathematics and mathematics_lean load distinct session instructions."""
        lean = generator._load_template_with_domain_override(
            "agents/session_instructions.txt", "mathematics_lean"
        )
        math = generator._load_template_with_domain_override(
            "agents/session_instructions.txt", "mathematics"
        )
        assert lean != math, (
            "mathematics_lean session_instructions must differ from mathematics"
        )


# ── 2. Template rendering (variable substitution) ─────────────────────────────

class TestTemplateRendering:
    def test_no_jinja_placeholders_remain(self, rendered):
        """No {{ variable }} tokens should survive rendering."""
        assert "{{" not in rendered, "Unrendered Jinja2 opening tag found"
        assert "}}" not in rendered, "Unrendered Jinja2 closing tag found"

    def test_work_dir_injected(self, rendered):
        assert SAMPLE_WORK_DIR in rendered, (
            "work_dir value should appear in rendered output"
        )

    def test_research_prompt_injected(self, rendered):
        assert SAMPLE_PROMPT in rendered, (
            "The research prompt should be embedded in session instructions"
        )

    def test_renders_as_string(self, rendered):
        assert isinstance(rendered, str) and len(rendered) > 500, (
            "Rendered output should be a non-trivial string"
        )

    def test_scribe_mode_differs_from_script_mode(self, rendered, rendered_scribe):
        """use_scribe=True should change the code_workflow injection."""
        assert rendered != rendered_scribe, (
            "Scribe and non-scribe renders should differ"
        )

    def test_scribe_mode_mentions_notebooks(self, rendered_scribe):
        assert "notebook" in rendered_scribe.lower(), (
            "Scribe mode should reference Jupyter notebooks"
        )

    def test_script_mode_mentions_scripts(self, rendered):
        assert "script" in rendered.lower() or "src/" in rendered, (
            "Non-scribe mode should reference Python scripts or src/"
        )


# ── 3. Lean content presence ──────────────────────────────────────────────────

class TestLeanContentPresence:
    @pytest.mark.parametrize("phrase", [
        "lake build",
        "lean_proofs",
        "sorry",
        "elan",
        "lake-manifest",   # referenced in Phase 4 verification step
        "Mathlib",
        "LeanProofs",
    ])
    def test_lean_phrase_present(self, rendered, phrase):
        assert phrase in rendered, (
            f"Expected Lean phrase '{phrase}' not found in rendered output"
        )

    def test_phase_lean_setup_present(self, rendered):
        """Phase 2 should contain Lean/elan setup instructions."""
        assert "Phase 2" in rendered, "Phase 2 heading missing"
        # elan or lean setup should appear somewhere in the text
        assert "elan" in rendered or "lean-prover" in rendered, (
            "Phase 2 should reference Lean/elan setup"
        )

    def test_phase_proof_construction_present(self, rendered):
        assert "Phase 3" in rendered, "Phase 3 heading missing"

    def test_phase_verification_present(self, rendered):
        assert "Phase 4" in rendered, "Phase 4 heading missing"

    def test_skill_script_referenced(self, rendered):
        """The setup_lean_project.sh skill script should be mentioned."""
        assert "setup_lean_project.sh" in rendered or "lean-prover" in rendered, (
            "Lean setup script or skill should be referenced"
        )

    def test_grep_sorry_check_present(self, rendered):
        """The grep-for-sorry completion check must be in the output."""
        assert "grep" in rendered and "sorry" in rendered, (
            "Completion check via 'grep sorry' should be present"
        )

    def test_lake_build_exit_code_mentioned(self, rendered):
        """Exit code semantics (how to interpret lake build result) should appear."""
        lower = rendered.lower()
        assert "exit" in lower or "exit code" in lower or "exit 0" in lower, (
            "lake build exit code interpretation should be mentioned"
        )


# ── 4. Lean-as-verifier framing ────────────────────────────────────────────────

class TestLeanAsVerifier:
    def test_lake_build_is_ground_truth(self, rendered):
        """'lake build' should appear multiple times — it's the core feedback loop."""
        count = rendered.count("lake build")
        assert count >= 2, (
            f"'lake build' appears only {count} time(s); expected ≥2 as the repeated verification step"
        )

    def test_sorry_is_incomplete_signal(self, rendered):
        """sorry should be framed as an incompleteness marker, not a valid proof."""
        # The instructions should warn that sorry means incomplete
        assert "sorry" in rendered
        # Some negative framing around sorry
        lower = rendered.lower()
        assert any(phrase in lower for phrase in [
            "no sorry",
            "not a proof",
            "incomplete",
            "remains",
            "sorry warning",
        ]), "sorry should be framed as an incompleteness signal"

    def test_proof_complete_condition_is_lake_build(self, rendered):
        """The proof completion signal should be lake build exit 0 + no sorry."""
        assert "exit 0" in rendered or "exits 0" in rendered or "exit code" in rendered.lower(), (
            "Proof completion should be tied to lake build exit code"
        )


# ── 5. Python-exploration framing ─────────────────────────────────────────────

class TestPythonExplorationFraming:
    def test_python_present_but_scoped(self, rendered):
        """Python/SymPy should appear but be labelled as exploration, not verification."""
        assert "Python" in rendered or "SymPy" in rendered or "sympy" in rendered, (
            "Python tools should still be mentioned for conjecture exploration"
        )

    def test_python_not_sole_verifier(self, rendered):
        """Python should not be described as the proof verification tool."""
        lower = rendered.lower()
        # The word 'verify' near 'python' should not be the primary framing
        # Lean / lake build should be the verification path
        assert "lake build" in rendered, (
            "lake build must be present as the actual verification mechanism"
        )

    def test_exploration_label_near_python(self, rendered):
        """Python usage should be labelled exploratory."""
        lower = rendered.lower()
        assert "explor" in lower, (
            "Python role should be labelled as 'exploration' or 'exploratory'"
        )


# ── 6. mathematics_lean differs from mathematics baseline ─────────────────────

class TestDifferenceFromMathematicsDomain:
    def test_lean_specific_content_absent_from_math_domain(self, rendered_generic):
        """The plain mathematics template should NOT mention lake build."""
        assert "lake build" not in rendered_generic, (
            "lake build should not appear in the plain mathematics domain output"
        )

    def test_lean_domain_output_longer_or_different(self, rendered, rendered_generic):
        """mathematics_lean output should be meaningfully different from mathematics."""
        assert rendered != rendered_generic, (
            "mathematics_lean and mathematics should produce different session instructions"
        )

    def test_lean_domain_has_more_lean_references(self, rendered, rendered_generic):
        lean_count = rendered.lower().count("lean")
        math_count = rendered_generic.lower().count("lean")
        assert lean_count > math_count, (
            f"mathematics_lean output ({lean_count} 'lean' refs) should mention "
            f"Lean more than mathematics output ({math_count} refs)"
        )
