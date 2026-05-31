"""
Unit tests for the mathematics_lean resource finder template.

The resource finder is the first agent in the pipeline. For mathematics_lean
it has an extra Phase 3 (Mathlib Lemma Catalog) not present in other domains.
These tests verify:

  1. Domain override resolution  — mathematics_lean loads its own template
  2. Template rendering          — idea content is injected; no bare {{ }}
  3. Phase 3 (Mathlib catalog)   — heading, all four steps, naming conventions,
                                   #check workflow, fallback guidance
  4. Lean project boundary       — resource finder must NOT set up Lean project
  5. Phase ordering              — 1 → 2 → 3 → 4 → 5 in rendered text
  6. literature_review.md format — Mathlib Lemma Catalog section is specified
  7. resources.md format         — Mathlib Prerequisites table is specified
  8. Completion marker           — counts Mathlib lemmas (not just papers)
  9. Differences from baselines  — generic and plain-math templates lack Phase 3
"""

import sys
import re
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from templates.prompt_generator import PromptGenerator

TEMPLATES_DIR = REPO_ROOT / "templates"
LEAN_RF_PATH  = TEMPLATES_DIR / "domains" / "mathematics_lean" / "resource_finder.txt"

# ── Sample ideas ───────────────────────────────────────────────────────────────

LEAN_IDEA = {
    "idea": {
        "title": "Formal verification of Ramsey-type bounds",
        "domain": "mathematics_lean",
        "hypothesis": "For every graph G with chromatic number > k, G contains K_{k+1} as a minor.",
        "background": {},
    }
}

MATH_IDEA = {
    "idea": {
        "title": "Ramsey bounds via probabilistic method",
        "domain": "mathematics",
        "hypothesis": "Same hypothesis — plain math domain.",
        "background": {},
    }
}

GENERIC_IDEA = {
    "idea": {
        "title": "A machine learning experiment",
        "domain": "machine_learning",
        "hypothesis": "Fine-tuning beats RAG for domain-specific tasks.",
        "background": {},
    }
}


@pytest.fixture
def gen():
    return PromptGenerator(TEMPLATES_DIR)


@pytest.fixture
def rendered(gen):
    return gen.generate_resource_finder_prompt(LEAN_IDEA)


@pytest.fixture
def rendered_math(gen):
    return gen.generate_resource_finder_prompt(MATH_IDEA)


@pytest.fixture
def rendered_generic(gen):
    return gen.generate_resource_finder_prompt(GENERIC_IDEA)


# ── 1. Domain override resolution ─────────────────────────────────────────────

class TestDomainOverrideResolution:
    def test_lean_override_file_exists(self):
        assert LEAN_RF_PATH.exists(), f"Override not found: {LEAN_RF_PATH}"

    def test_lean_template_differs_from_generic_fallback(self, gen):
        lean    = gen._load_template_with_domain_override(
            "agents/resource_finder.txt", "mathematics_lean"
        )
        generic = gen.load_template("agents/resource_finder.txt")
        assert lean != generic

    def test_lean_template_differs_from_plain_math(self, gen):
        lean = gen._load_template_with_domain_override(
            "agents/resource_finder.txt", "mathematics_lean"
        )
        math = gen._load_template_with_domain_override(
            "agents/resource_finder.txt", "mathematics"
        )
        assert lean != math


# ── 2. Template rendering ──────────────────────────────────────────────────────

class TestTemplateRendering:
    def test_no_jinja_placeholders_remain(self, rendered):
        assert "{{" not in rendered and "}}" not in rendered

    def test_idea_title_injected(self, rendered):
        assert "Ramsey-type bounds" in rendered

    def test_idea_hypothesis_injected(self, rendered):
        assert "chromatic number" in rendered

    def test_idea_domain_injected(self, rendered):
        assert "mathematics_lean" in rendered

    def test_result_is_substantial_string(self, rendered):
        assert isinstance(rendered, str) and len(rendered) > 1000


# ── 3. Phase 3 — Mathlib Lemma Catalog ────────────────────────────────────────

class TestMathlibCatalogPhase:
    def test_phase3_heading_present(self, rendered):
        assert "PHASE 3" in rendered, "Phase 3 heading must be in rendered output"

    def test_phase3_mathlib_label(self, rendered):
        assert "MATHLIB" in rendered.upper() or "Mathlib Lemma Catalog" in rendered, (
            "Phase 3 must be labelled as the Mathlib lemma catalog"
        )

    def test_phase3_step1_naming_conventions(self, rendered):
        """Step 1 documents Mathlib naming conventions."""
        assert "Nat." in rendered or "Nat.*" in rendered, (
            "Mathlib Nat.* namespace convention must be documented"
        )
        assert "add_comm" in rendered, (
            "Example lemma name (add_comm) must appear in naming conventions"
        )

    def test_phase3_step1_multiple_namespaces(self, rendered):
        """Several type namespaces must be shown, not just Nat."""
        for ns in ["Nat.", "Int.", "Real.", "Finset.", "List."]:
            assert ns in rendered, f"Namespace '{ns}' missing from naming conventions"

    def test_phase3_step2_hash_check_verification(self, rendered):
        """Step 2 must show the #check approach for verifying lemma names."""
        assert "#check" in rendered, (
            "#check must be documented as the lemma-name verification tool"
        )
        assert "Nat.add_comm" in rendered, (
            "A concrete #check example (Nat.add_comm) must be shown"
        )

    def test_phase3_step2_lean_scratch_file(self, rendered):
        """Step 2 must show the lean_scratch / Check.lean workflow."""
        assert "lean_scratch" in rendered, (
            "lean_scratch directory must be part of the #check workflow"
        )
        assert "Check.lean" in rendered, (
            "Check.lean scratch file must be shown in Phase 3 Step 2"
        )

    def test_phase3_step2_fallback_when_lean_unavailable(self, rendered):
        """When lean binary is absent, web search is the documented fallback."""
        assert "leanprover-community.github.io/mathlib4_docs" in rendered, (
            "Web search fallback URL must be present for when lean is unavailable"
        )

    def test_phase3_step3_search_for_formalizations(self, rendered):
        """Step 3 must instruct searching for existing Lean formalizations."""
        lower = rendered.lower()
        assert "lean formalization" in lower or "existing lean" in lower, (
            "Phase 3 Step 3 must tell the agent to search for existing formalizations"
        )

    def test_phase3_step3_mathlib4_github_mentioned(self, rendered):
        assert "leanprover-community/mathlib4" in rendered, (
            "Mathlib4 GitHub URL must be referenced for formalization search"
        )

    def test_phase3_step4_lemma_table_format(self, rendered):
        """Step 4 must show the Mathlib lemma table with the required columns."""
        assert "Mathlib Name" in rendered, "Table column 'Mathlib Name' must be shown"
        assert "Informal Result" in rendered or "Informal" in rendered, (
            "Table column for informal result must be shown"
        )
        # Verified / Not in Mathlib status symbols
        assert "✓" in rendered and "✗" in rendered, (
            "Table must show ✓ (in Mathlib) and ✗ (not in Mathlib) status symbols"
        )

    def test_phase3_step4_table_has_concrete_examples(self, rendered):
        """The table must contain at least one worked example row."""
        assert "Nat.add_comm" in rendered or "Finset.sum_range_succ" in rendered, (
            "Phase 3 Step 4 table must contain a concrete Mathlib lemma example"
        )

    def test_phase3_critical_label(self, rendered):
        """Phase 3 must be marked as CRITICAL (it's unique to this domain)."""
        # Find Phase 3 section and check nearby text
        idx = rendered.upper().find("PHASE 3")
        assert idx != -1
        window = rendered[idx:idx + 300].upper()
        assert "CRITICAL" in window, (
            "Phase 3 must be labelled CRITICAL to signal its importance"
        )


# ── 4. Lean project boundary ───────────────────────────────────────────────────

class TestLeanProjectBoundary:
    def test_explicit_do_not_setup_lean(self, rendered):
        """The resource finder must explicitly tell the agent NOT to set up Lean."""
        lower = rendered.lower()
        assert "do not set up the lean project" in lower or (
            "do not" in lower and "lean" in lower and "setup" in lower
        ) or "experiment runner" in lower and "lean setup" in lower.replace("\n", " "), (
            "Resource finder must explicitly state Lean project setup is NOT its job"
        )

    def test_no_lake_build_in_resource_finder(self, rendered):
        """lake build must NOT be a primary instruction — that belongs to the
        experiment runner. Only the lean_scratch verification snippet may run lean."""
        # lake build should not appear as a primary step
        # It may appear inside the scratch-file snippet (lean lean_scratch/...)
        # but should NOT appear as a phase instruction
        occurrences = [m.start() for m in re.finditer(r"lake build", rendered)]
        # If it appears at all, it must only be inside the scratch-file context
        # (i.e. not as a standalone phase step)
        for pos in occurrences:
            window = rendered[max(0, pos - 100):pos + 100]
            assert "scratch" in window.lower() or "setup" in window.lower() or \
                   "verify" in window.lower(), (
                "'lake build' should only appear in a scratch/verification context "
                "inside the resource finder, not as a phase instruction"
            )

    def test_experiment_runner_owns_lean_setup(self, rendered):
        """The boundary must explicitly name the experiment runner as owner."""
        assert "experiment runner" in rendered.lower(), (
            "Resource finder must reference the experiment runner as responsible for Lean setup"
        )

    def test_dont_list_mentions_lean_project(self, rendered):
        """The DON'T list must warn against setting up the Lean project."""
        lower = rendered.lower()
        assert "don't" in lower or "dont" in lower or "✗" in rendered, (
            "A DON'T / best-practice list must exist"
        )
        # The lean-project warning must exist somewhere
        assert "lean project" in lower or ("set up" in lower and "lean" in lower), (
            "DON'T list must warn against setting up the Lean project"
        )


# ── 5. Phase ordering ─────────────────────────────────────────────────────────

class TestPhaseOrdering:
    """Phases must appear in the correct order in the rendered text."""

    def _phase_position(self, rendered: str, n: int) -> int:
        match = re.search(rf"PHASE {n}[^0-9]", rendered)
        assert match, f"PHASE {n} not found in rendered output"
        return match.start()

    def test_phase1_before_phase2(self, rendered):
        assert self._phase_position(rendered, 1) < self._phase_position(rendered, 2)

    def test_phase2_before_phase3(self, rendered):
        assert self._phase_position(rendered, 2) < self._phase_position(rendered, 3)

    def test_phase3_before_phase4(self, rendered):
        assert self._phase_position(rendered, 3) < self._phase_position(rendered, 4)

    def test_phase4_before_phase5(self, rendered):
        assert self._phase_position(rendered, 4) < self._phase_position(rendered, 5)

    def test_phase3_is_mathlib_not_tools(self, rendered):
        """Phase 3 must be the Mathlib catalog, Phase 4 must be computational tools."""
        p3_start = self._phase_position(rendered, 3)
        p4_start = self._phase_position(rendered, 4)
        phase3_text = rendered[p3_start:p4_start].upper()
        assert "MATHLIB" in phase3_text, (
            "Phase 3 content must be about Mathlib, not computational tools"
        )

    def test_phase4_is_computational_tools(self, rendered):
        p4_start = self._phase_position(rendered, 4)
        p5_start = self._phase_position(rendered, 5)
        phase4_text = rendered[p4_start:p5_start].upper()
        assert "TOOL" in phase4_text or "SYMPY" in phase4_text or "PYTHON" in phase4_text, (
            "Phase 4 content must be about computational tools"
        )


# ── 6. literature_review.md output format ─────────────────────────────────────

class TestLiteratureReviewFormat:
    def test_mathlib_lemma_catalog_section_specified(self, rendered):
        """The literature_review.md template must include a Mathlib Lemma Catalog section."""
        assert "Mathlib Lemma Catalog" in rendered, (
            "literature_review.md format must include a 'Mathlib Lemma Catalog' section"
        )

    def test_existing_lean_formalizations_section_specified(self, rendered):
        assert "Existing Lean Formalizations" in rendered, (
            "literature_review.md format must include 'Existing Lean Formalizations' section"
        )

    def test_recommendations_split_mathlib_vs_scratch(self, rendered):
        """Recommendations must distinguish 'cite from Mathlib' vs 'prove from scratch'."""
        lower = rendered.lower()
        assert "cite" in lower and "mathlib" in lower, (
            "Recommendations section must mention citing from Mathlib"
        )
        assert "prove from scratch" in lower or "prove" in lower and "scratch" in lower, (
            "Recommendations section must mention what must be proved from scratch"
        )

    def test_lean_tactics_mentioned_in_recommendations(self, rendered):
        """The proof strategy recommendation must mention Lean tactics."""
        lower = rendered.lower()
        assert "lean tactic" in lower or "tactic" in lower, (
            "Recommendations must mention Lean tactics likely useful for each step"
        )


# ── 7. resources.md format ────────────────────────────────────────────────────

class TestResourcesMdFormat:
    def test_mathlib_prerequisites_table_specified(self, rendered):
        assert "Mathlib Prerequisites" in rendered, (
            "resources.md format must include a 'Mathlib Prerequisites' table"
        )

    def test_mathlib_prerequisites_table_has_columns(self, rendered):
        """The Mathlib Prerequisites table must have the right columns."""
        assert "Mathlib Name" in rendered, "Column 'Mathlib Name' must appear in table"
        assert "Used For" in rendered, "Column 'Used For' must appear in table"

    def test_recommendations_split_cite_vs_prove(self, rendered):
        """resources.md recommendations must split Mathlib cites from scratch proofs."""
        assert "Mathlib lemmas to cite" in rendered or (
            "cite directly" in rendered.lower()
        ), "Recommendations must list Mathlib lemmas to cite"
        assert "proved from scratch" in rendered.lower() or (
            "prove from scratch" in rendered.lower()
        ), "Recommendations must list lemmas to prove from scratch"


# ── 8. Completion marker ──────────────────────────────────────────────────────

class TestCompletionMarker:
    def test_completion_marker_file_present(self, rendered):
        assert ".resource_finder_complete" in rendered, (
            "Completion marker file must be mentioned"
        )

    def test_completion_marker_counts_mathlib_lemmas(self, rendered):
        """The marker must record Mathlib lemma count, not just papers."""
        assert "Mathlib lemmas identified" in rendered, (
            "Completion marker must count Mathlib lemmas found, "
            "not just papers downloaded"
        )

    def test_final_checklist_includes_mathlib_check(self, rendered):
        """The final checklist must include a Mathlib-specific verification step."""
        lower = rendered.lower()
        assert "#check" in rendered and "checklist" in lower or (
            "mathlib lemma" in lower and ("✓" in rendered or "verified" in lower)
        ), "Final checklist must include the Mathlib lemma #check step"


# ── 9. Differences from baselines ─────────────────────────────────────────────

class TestBaselineDifferences:
    def test_phase3_absent_from_generic_resource_finder(self, rendered_generic):
        """Generic (ML) resource finder must NOT have the Mathlib catalog phase."""
        assert "Mathlib Lemma Catalog" not in rendered_generic, (
            "Mathlib Lemma Catalog must be unique to mathematics_lean"
        )
        assert "#check" not in rendered_generic, (
            "#check verification must be absent from generic resource finder"
        )

    def test_phase3_absent_from_plain_math_resource_finder(self, rendered_math):
        """Plain mathematics resource finder must NOT have Phase 3 Mathlib catalog."""
        assert "Mathlib Lemma Catalog" not in rendered_math, (
            "Mathlib Lemma Catalog must be unique to mathematics_lean, not plain mathematics"
        )

    def test_lean_domain_has_more_mathlib_references(self, rendered, rendered_math):
        lean_count = rendered.count("Mathlib")
        math_count = rendered_math.count("Mathlib")
        assert lean_count > math_count, (
            f"mathematics_lean ({lean_count} refs) should mention Mathlib more "
            f"than plain mathematics ({math_count} refs)"
        )

    def test_do_not_setup_lean_absent_from_plain_math(self, rendered_math):
        """The specific 'Do NOT set up the Lean project here' boundary note
        must not appear in the plain mathematics resource finder."""
        lower = rendered_math.lower()
        # The exact boundary phrase unique to mathematics_lean
        assert "do not set up the lean project" not in lower and (
            "experiment runner phase handles lean setup" not in lower
        ), (
            "The Lean-project boundary note should only appear in mathematics_lean, "
            "not in plain mathematics"
        )
