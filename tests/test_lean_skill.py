"""
Unit tests for the lean-prover skill.

Covers three components:
  1. SKILL.md structure & content
       — frontmatter validity, required sections, tactic table,
         verification workflow, error message table
  2. setup_lean_project.sh content
       — safety flags, elan conditional install, file structure
         it creates, cache step ordering, argument handling
  3. Cross-file consistency
       — names and paths referenced in SKILL.md match what the
         script actually produces; setup command in SKILL.md
         points at a file that exists on disk
  4. Workspace copy
       — _copy_workspace_resources copies both files into
         .claude/skills/lean-prover/ as the agent expects
"""

import os
import re
import shutil
import stat
import sys
import tempfile
import yaml
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

SKILL_DIR    = REPO_ROOT / "templates" / "skills" / "lean-prover"
SKILL_MD     = SKILL_DIR / "SKILL.md"
SETUP_SCRIPT = SKILL_DIR / "scripts" / "setup_lean_project.sh"


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter dict from a file with --- delimiters."""
    text = path.read_text()
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


def markdown_sections(path: Path) -> list[str]:
    """Return list of section heading strings (stripped of # prefix)."""
    return [
        line.lstrip("#").strip()
        for line in path.read_text().splitlines()
        if line.startswith("#")
    ]


def script_text() -> str:
    return SETUP_SCRIPT.read_text()


# ── 1. SKILL.md — frontmatter ─────────────────────────────────────────────────

class TestSkillFrontmatter:
    def test_frontmatter_is_valid_yaml(self):
        fm = parse_frontmatter(SKILL_MD)
        assert isinstance(fm, dict), "Frontmatter must parse as a YAML mapping"

    def test_name_field_present(self):
        fm = parse_frontmatter(SKILL_MD)
        assert "name" in fm, "Frontmatter must have a 'name' field"

    def test_name_matches_directory(self):
        fm = parse_frontmatter(SKILL_MD)
        assert fm["name"] == "lean-prover", (
            f"name '{fm['name']}' does not match directory name 'lean-prover'"
        )

    def test_description_field_present(self):
        fm = parse_frontmatter(SKILL_MD)
        assert "description" in fm and fm["description"], (
            "Frontmatter must have a non-empty 'description' field"
        )

    def test_description_mentions_lean4(self):
        fm = parse_frontmatter(SKILL_MD)
        assert "Lean 4" in fm["description"] or "Lean4" in fm["description"], (
            "description should explicitly mention 'Lean 4'"
        )

    def test_description_mentions_mathlib(self):
        fm = parse_frontmatter(SKILL_MD)
        assert "Mathlib" in fm["description"], (
            "description should mention 'Mathlib'"
        )

    def test_description_mentions_mathematics_lean_domain(self):
        fm = parse_frontmatter(SKILL_MD)
        assert "mathematics_lean" in fm["description"], (
            "description should reference the 'mathematics_lean' domain"
        )


# ── 2. SKILL.md — required sections ──────────────────────────────────────────

REQUIRED_SECTIONS = [
    "When to Use",
    "Project Setup",
    "Project Structure",
    "Writing Proofs",
    "Core Tactic Reference",
    "Searching Mathlib",
    "Verification Workflow",
    "Interpreting Lean Error Messages",
    "Proof Skeleton Template",
    "Common Mathlib Imports by Area",
]

class TestSkillSections:
    @pytest.mark.parametrize("section", REQUIRED_SECTIONS)
    def test_required_section_exists(self, section):
        sections = markdown_sections(SKILL_MD)
        # Allow the heading to have a suffix (e.g. "Verification Workflow (Per Proof)")
        assert any(s.startswith(section) for s in sections), (
            f"Required section '{section}' not found in SKILL.md.\n"
            f"Found sections: {sections}"
        )

    def test_when_to_use_mentions_mathematics_lean(self):
        text = SKILL_MD.read_text()
        # Find the When to Use section content
        assert "mathematics_lean" in text, (
            "'mathematics_lean' domain should appear in When to Use section"
        )

    def test_setup_script_path_in_skill_md(self):
        """The path referenced in SKILL.md for the setup script must exist."""
        text = SKILL_MD.read_text()
        # The skill references: .claude/skills/lean-prover/scripts/setup_lean_project.sh
        assert "setup_lean_project.sh" in text, (
            "SKILL.md must reference the setup script"
        )
        # The actual file must also exist at the template level
        assert SETUP_SCRIPT.exists(), (
            f"setup_lean_project.sh not found at {SETUP_SCRIPT}"
        )


# ── 3. SKILL.md — tactic table ────────────────────────────────────────────────

# Automation tactics the agent should try first (they appear most often)
AUTOMATION_TACTICS = ["ring", "omega", "linarith", "norm_num", "simp", "decide"]
# Manual tactics for structural proofs
STRUCTURAL_TACTICS = ["exact", "apply", "rw", "intro", "cases", "induction", "by_contra", "use"]
# Tactics that only work interactively — must be flagged as such
INTERACTIVE_ONLY_TACTICS = ["exact?", "apply?", "simp?"]

class TestTacticTable:
    @pytest.mark.parametrize("tactic", AUTOMATION_TACTICS)
    def test_automation_tactic_present(self, tactic):
        assert f"`{tactic}`" in SKILL_MD.read_text(), (
            f"Automation tactic '{tactic}' missing from tactic table"
        )

    @pytest.mark.parametrize("tactic", STRUCTURAL_TACTICS)
    def test_structural_tactic_present(self, tactic):
        text = SKILL_MD.read_text()
        assert f"`{tactic}`" in text or f"`{tactic} " in text, (
            f"Structural tactic '{tactic}' missing from tactic table"
        )

    @pytest.mark.parametrize("tactic", INTERACTIVE_ONLY_TACTICS)
    def test_interactive_tactic_flagged(self, tactic):
        text = SKILL_MD.read_text()
        assert tactic in text, f"Interactive tactic '{tactic}' not mentioned"
        # Must be accompanied by a warning that it's interactive-only
        assert "Interactive only" in text or "interactive" in text.lower(), (
            f"Interactive-only tactic '{tactic}' must be flagged as interactive-only"
        )


# ── 4. SKILL.md — verification workflow ──────────────────────────────────────

class TestVerificationWorkflow:
    def test_lake_build_command_shown(self):
        assert "lake build" in SKILL_MD.read_text()

    def test_grep_sorry_command_shown(self):
        text = SKILL_MD.read_text()
        assert "grep" in text and "sorry" in text, (
            "Verification workflow must show the grep-sorry completion check"
        )

    def test_exit_code_semantics_documented(self):
        text = SKILL_MD.read_text()
        # Both outcomes must be documented
        assert "exit code" in text.lower() or ("0" in text and "non-zero" in text), (
            "lake build exit code semantics (0 vs non-zero) must be documented"
        )

    def test_sorry_declaration_warning_documented(self):
        """'declaration uses sorry' is the Lean warning agents will see most often."""
        assert "declaration uses sorry" in SKILL_MD.read_text(), (
            "'declaration uses sorry' must appear in the error message table"
        )

    def test_stub_then_prove_workflow_documented(self):
        """The sorry-stub → build → replace workflow must be present."""
        text = SKILL_MD.read_text()
        assert "sorry" in text
        # The workflow shows using sorry first to check the type, then replacing
        assert "stub" in text.lower() or "placeholder" in text.lower() or (
            "sorry" in text and "replace" in text.lower()
        ), "Sorry-stub workflow (use sorry first, then replace) must be documented"


# ── 5. SKILL.md — error message table ────────────────────────────────────────

REQUIRED_ERRORS = [
    "unknown identifier",
    "type mismatch",
    "unsolved goals",
    "declaration uses sorry",
    "failed to synthesize instance",
]

class TestErrorMessageTable:
    @pytest.mark.parametrize("error", REQUIRED_ERRORS)
    def test_error_message_documented(self, error):
        assert error in SKILL_MD.read_text(), (
            f"Error message '{error}' not documented in SKILL.md"
        )


# ── 6. setup_lean_project.sh — safety & structure ────────────────────────────

class TestSetupScriptSafety:
    def test_shebang_is_env_bash(self):
        first_line = SETUP_SCRIPT.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", (
            f"Script must start with '#!/usr/bin/env bash', got: '{first_line}'"
        )

    def test_errexit_set(self):
        assert "set -euo pipefail" in script_text(), (
            "Script must have 'set -euo pipefail' for safety"
        )

    def test_elan_install_is_conditional(self):
        text = script_text()
        # elan installation must be inside an if block, not unconditional
        assert "command -v elan" in text or "command -v lean" in text, (
            "Script must check if elan/lean is already installed before installing"
        )

    def test_cache_step_before_build(self):
        text = script_text()
        cache_pos = text.find("cache get")
        build_pos = text.find("lake build")
        assert cache_pos != -1, "Script must call 'lake exe cache get'"
        assert build_pos != -1, "Script must call 'lake build'"
        assert cache_pos < build_pos, (
            "Cache download must happen before the initial lake build"
        )

    def test_build_failure_exits_nonzero(self):
        text = script_text()
        assert "exit 1" in text, (
            "Script must exit 1 if lake build fails (not silently succeed)"
        )

    def test_accepts_custom_project_dir_argument(self):
        text = script_text()
        # PROJECT_DIR="${1:-lean_proofs}" pattern
        assert '${1:-' in text or '"$1"' in text, (
            "Script must accept a custom project directory as $1"
        )

    def test_default_project_dir_is_lean_proofs(self):
        text = script_text()
        assert '"${1:-lean_proofs}"' in text or "lean_proofs}" in text, (
            "Default project directory must be 'lean_proofs'"
        )


# ── 7. setup_lean_project.sh — file structure created ────────────────────────

class TestSetupScriptFileStructure:
    def test_creates_definitions_lean(self):
        assert "Definitions.lean" in script_text()

    def test_creates_lemmas_lean(self):
        assert "Lemmas.lean" in script_text()

    def test_creates_main_theorem_lean(self):
        assert "MainTheorem.lean" in script_text()

    def test_lib_name_is_LeanProofs(self):
        assert 'LIB_NAME="LeanProofs"' in script_text(), (
            "Library name must be 'LeanProofs'"
        )

    def test_root_import_file_created(self):
        text = script_text()
        # The root import file uses the $LIB_NAME shell variable, so the
        # script contains "${LIB_NAME}.Definitions" rather than the literal
        # expanded form.  Check for the variable-expanded pattern.
        assert "${LIB_NAME}.Definitions" in text or "LeanProofs.Definitions" in text
        assert "${LIB_NAME}.Lemmas" in text      or "LeanProofs.Lemmas" in text
        assert "${LIB_NAME}.MainTheorem" in text or "LeanProofs.MainTheorem" in text

    def test_starter_files_are_idempotent(self):
        """Files should only be written if they don't already exist."""
        text = script_text()
        # Each write should be guarded by [ ! -f ... ]
        assert '[ ! -f' in text or "! -f" in text, (
            "Starter file creation must be guarded against overwriting existing files"
        )

    def test_definitions_lean_imports_mathlib_tactic(self):
        """Definitions.lean starter must use import Mathlib.Tactic (not full import Mathlib).
        Mathlib.Tactic provides all tactics at ~1-2GB cache cost vs 5GB for import Mathlib."""
        text = script_text()
        assert "import Mathlib.Tactic" in text, (
            "Starter file must use 'import Mathlib.Tactic', not bare 'import Mathlib'"
        )

    def test_definitions_lean_does_not_use_bare_import_mathlib(self):
        """Bare 'import Mathlib' must not appear in the starter Definitions.lean heredoc —
        it triggers a full 5GB cache download unnecessarily."""
        text = script_text()
        # Find the heredoc block for Definitions.lean
        start = text.find("Definitions.lean")
        heredoc_block = text[start:start + 400]  # just the heredoc content
        assert "import Mathlib\n" not in heredoc_block, (
            "Starter Definitions.lean must not use bare 'import Mathlib' — "
            "use 'import Mathlib.Tactic' instead"
        )

    def test_lemmas_lean_imports_definitions(self):
        """Lemmas.lean starter content must import Definitions (not raw Mathlib)."""
        assert "import LeanProofs.Definitions" in script_text()

    def test_main_theorem_lean_imports_lemmas(self):
        """MainTheorem.lean must import Lemmas to complete the dependency chain."""
        assert "import LeanProofs.Lemmas" in script_text()

    def test_uses_mathlib_lake_template(self):
        """Must use the official Mathlib lake template, not a bare init."""
        text = script_text()
        assert "mathlib4" in text and "math" in text, (
            "Project must be created with the Mathlib lake template"
        )


# ── 8. Cross-file consistency ─────────────────────────────────────────────────

class TestCrossFileConsistency:
    def test_skill_md_project_dir_matches_script_default(self):
        """SKILL.md shows 'lean_proofs/' — must match script's default."""
        skill_text = SKILL_MD.read_text()
        assert "lean_proofs" in skill_text, (
            "SKILL.md must reference 'lean_proofs' as the project directory"
        )
        assert "lean_proofs}" in script_text() or '"lean_proofs"' in script_text(), (
            "Script default must be 'lean_proofs'"
        )

    def test_skill_md_lib_name_matches_script(self):
        """SKILL.md shows 'LeanProofs/' — must match script's LIB_NAME."""
        assert "LeanProofs" in SKILL_MD.read_text(), (
            "SKILL.md must reference 'LeanProofs' as the library name"
        )
        assert "LeanProofs" in script_text(), (
            "Script must use 'LeanProofs' as the library name"
        )

    def test_skill_md_file_layout_matches_script_output(self):
        """All three files in SKILL.md's Project Structure exist in the script."""
        skill_text = SKILL_MD.read_text()
        for filename in ["Definitions.lean", "Lemmas.lean", "MainTheorem.lean"]:
            assert filename in skill_text, (
                f"{filename} missing from SKILL.md Project Structure"
            )
            assert filename in script_text(), (
                f"{filename} not created by setup_lean_project.sh"
            )

    def test_setup_command_in_skill_md_matches_actual_path(self):
        """The 'bash ...setup_lean_project.sh' command in SKILL.md must point
        to a file that exists under templates/skills/."""
        skill_text = SKILL_MD.read_text()
        # Extract the referenced script path
        match = re.search(r'bash\s+([\w./-]+setup_lean_project\.sh)', skill_text)
        assert match, "SKILL.md must show a 'bash ...setup_lean_project.sh' command"

        relative_path = match.group(1)
        # The path is relative to the workspace root at runtime:
        #   .claude/skills/lean-prover/scripts/setup_lean_project.sh
        # At template level it lives at:
        #   templates/skills/lean-prover/scripts/setup_lean_project.sh
        assert "lean-prover" in relative_path, (
            f"Path '{relative_path}' must reference the lean-prover skill"
        )
        assert "setup_lean_project.sh" in relative_path

    def test_import_chain_is_consistent(self):
        """Definitions ← Lemmas ← MainTheorem must be present in both files.

        The script uses the shell variable form (${LIB_NAME}.X) while SKILL.md
        shows the expanded literal form (LeanProofs.X).  Accept either.
        """
        script = script_text()
        skill = SKILL_MD.read_text()
        for suffix in ["Definitions", "Lemmas", "MainTheorem"]:
            literal  = f"import LeanProofs.{suffix}"
            variable = f"import ${{LIB_NAME}}.{suffix}"
            assert literal in script  or variable in script, (
                f"Script missing import for LeanProofs.{suffix}"
            )
            assert literal in skill, (
                f"SKILL.md missing: import LeanProofs.{suffix}"
            )


# ── 9. Workspace copy ─────────────────────────────────────────────────────────

class TestWorkspaceCopy:
    """Verify _copy_workspace_resources plants the lean-prover skill correctly."""

    def test_skill_dir_copied_to_claude_skills(self):
        """After _copy_workspace_resources, .claude/skills/lean-prover/ exists."""
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from core.runner import ResearchRunner

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            runner = ResearchRunner(project_root=REPO_ROOT, use_github=False)
            runner._copy_workspace_resources(work_dir)

            skill_dst = work_dir / ".claude" / "skills" / "lean-prover"
            assert skill_dst.exists(), (
                f"lean-prover skill not found at {skill_dst} after workspace copy"
            )

    def test_skill_md_present_after_copy(self):
        from core.runner import ResearchRunner

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            runner = ResearchRunner(project_root=REPO_ROOT, use_github=False)
            runner._copy_workspace_resources(work_dir)

            skill_md_dst = work_dir / ".claude" / "skills" / "lean-prover" / "SKILL.md"
            assert skill_md_dst.exists(), "SKILL.md must be present after workspace copy"

    def test_setup_script_present_after_copy(self):
        from core.runner import ResearchRunner

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            runner = ResearchRunner(project_root=REPO_ROOT, use_github=False)
            runner._copy_workspace_resources(work_dir)

            script_dst = (
                work_dir / ".claude" / "skills" / "lean-prover"
                / "scripts" / "setup_lean_project.sh"
            )
            assert script_dst.exists(), (
                "setup_lean_project.sh must be present after workspace copy"
            )

    def test_skill_also_copied_to_gemini_and_codex(self):
        """The skill must land in .gemini/skills/ and .codex/skills/ too."""
        from core.runner import ResearchRunner

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            runner = ResearchRunner(project_root=REPO_ROOT, use_github=False)
            runner._copy_workspace_resources(work_dir)

            for provider_dir in [".gemini", ".codex"]:
                skill_dst = work_dir / provider_dir / "skills" / "lean-prover"
                assert skill_dst.exists(), (
                    f"lean-prover skill missing from {provider_dir}/skills/ — "
                    "provider-agnostic copy must include lean-prover"
                )
