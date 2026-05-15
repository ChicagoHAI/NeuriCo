"""
Validators - Validate phase outputs before pipeline transitions.

This module provides deterministic and lightweight structural validation for research pipeline stages.
It returns structured checks that supprt future critic agents, retry logic, or human review.

Validation strategy:
- required artifact checks
- optional artifact visibility
- lightweight structural checks
- idea-specified expected output checks
- scientific due-diligence section checks for final reports
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

class StageValidator:
    """
    Validate whether each pipeline stage produced expected artifacts.

    It checks:
    - missing required files fail validation
    - missing optional files are recorded but do not fail
    - weak report structure can fail experiment validation
    - recoverable indicates the user can add/fix files and rerun
    
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    def validate_stage(self, stage_name: str, idea: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate one pipeline stage."""
        if stage_name == "resource_finder":
            return self._validate_resource_finder(idea)
        if stage_name == "experiment_runner":
            return self._validate_experiment_runner(idea)
        
        return {
            "passed": True,
            "recoverable": True,
            "summary": f"No validator implemented for stage '{stage_name}'.",
            "checks": [],
        }
    
    def _validate_resource_finder(self, idea: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate resource finder."""
        checks: List[Dict[str, Any]] = []
        passed = True

        required_paths = {
            "completion_marker": self.work_dir / ".resource_finder_complete",
            "literature_review": self.work_dir / "literature_review.md",
            "resources_catalog": self.work_dir / "resources.md",
        }

        optional_paths = {
            "papers_dir": self.work_dir / "papers",
            "datasets_dir": self.work_dir / "datasets",
            "code_dir": self.work_dir / "code",
        }

        for name, path in required_paths.items():
            check = self._path_check(name, path, required=True)
            checks.append(check)
            if not check["passed"]:
                passed = False

        for name, path in optional_paths.items():
            checks.append(self._path_check(name, path, required=False))

        lit_ok = self._markdown_has_minimum_sections(required_paths["literature_review"], min_headings=1)
        res_ok = self._markdown_has_minimum_sections(required_paths["resources_catalog"], min_headings=1)

        checks.append(self._boolean_check("literature_review_structure", lit_ok, required=True, detail="literature_review.md should contain at least one markdown heading."))
        checks.append(self._boolean_check("resource_catalog_structure", res_ok, required=True, detail="resources.md should contain at least one markdown heading."))
        if not lit_ok or not res_ok:
            passed = False

        return {
            "passed": passed,
            "recoverable": True,
            "summary": (
                "Resource finder validation passed."
                if passed
                else "Missing required outputs or structure for resource finder."
            ),
            "checks": checks,
        }

    def _validate_experiment_runner(self, idea: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate experiment runner."""
        checks: List[Dict[str, Any]] = []
        passed = True

        required_paths = {
            "report": self.work_dir / "REPORT.md",
            "readme": self.work_dir / "README.md",
            "logs_dir": self.work_dir / "logs",
        }

        optional_paths = {
            "planning": self.work_dir / "planning.md",
            "results_dir": self.work_dir / "results",
            "src_dir": self.work_dir / "src",
            "notebooks_dir": self.work_dir / "notebooks",
            "artifacts_dir": self.work_dir / "artifacts",
        }


        for name, path in required_paths.items():
            check = self._path_check(name, path, required=True)
            checks.append(check)
            if not check["passed"]:
                passed = False

        for name, path in optional_paths.items():
            checks.append(self._path_check(name, path, required=False))
        
        report_path = required_paths["report"]
        readme_path = required_paths["readme"]

        report_ok = self._markdown_has_minimum_sections(report_path, min_headings=3)
        readme_ok = self._markdown_has_minimum_sections(readme_path, min_headings=1)

        checks.append(self._boolean_check("report_structure", report_ok, required=True, detail="REPORT.md should contain multiple structured sections."))
        checks.append(self._boolean_check("readme_structure", readme_ok, required=True, detail="README.md should contain at least one markdown heading."))

        if not report_ok or not readme_ok:
            passed = False
        
        report_text = self._read_text(report_path)
        scientific_checks = self._scientific_due_diligence_checks(report_text)
        checks.extend(scientific_checks)

        required_science_checks = [check for check in scientific_checks if check.get("required")]
        if any(not check["passed"] for check in required_science_checks):
            passed = False
        
        checks.extend(self._expected_output_checks(idea))

        return {
            "passed": passed,
            "recoverable": True,
            "summary": (
                "Experiment runner validation passed."
                if passed
                else "Missing required outputs or structure for experiment runner."
            ),
            "checks": checks,
        }

    def _expected_output_checks(self, idea: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Record idea-specified expected outputs.
        Expected outputs are schema-level requirements, but often describe abstract outputs rather than exact file paths.
        We record them now and leave exact schema/file validation for future extensions.
        """
        if not idea:
            return []
        
        checks: List[Dict[str, Any]] = []
        expected = idea.get("idea", {}).get("expected_outputs", []) or []

        for output in expected:
            output_type = output.get("type", "unknown")
            output_format = output.get("format", "unknown")
            checks.append(
                {
                    "name": f"expected_output_declared:{output_type}",
                    "path": f"format={output_format}",
                    "required": False,
                    "exists": True,
                    "passed": True,
                    "detail": "Expected output declared in idea spec.",
                }
            )
        return checks
    
    def _scientific_due_diligence_checks(self, report_text: str) -> List[Dict[str, Any]]:
        """
        Check key research reports.
        
        These checks align with the scientific-rigor template without launching a separate critic agent.
        """
        lowered = report_text.lower()
        checks = [
            (
                "report_has_methodology",
                any(term in lowered for term in ["methodology", "methods", "experimental design"]),
                True,
                "Report should explain the methodology or experimental design.",
            ),
            (
                "report_has_results",
                "result" in lowered,
                True,
                "Report should include results.",
            ),
            (
                "report_has_limitations",
                "limitation" in lowered or "threat" in lowered,
                True,
                "Report should acknowledge limitations or threats to validity.",
            ),
            (
                "report_has_baseline_discussion",
                "baseline" in lowered,
                False,
                "Report should discuss baselines where applicable.",
            ),
            (
                "report_has_statistical_discussion",
                any(term in lowered for term in ["p-value", "confidence interval", "statistical", "significance"]),
                False,
                "Report should discuss statistical validity where applicable.",
            ),
            (
                "report_has_reproducibility_info",
                any(term in lowered for term in ["reproduc", "seed", "environment", "dependency"]),
                False,
                "Report should include reproducibility details.",
            ),
        ]
        return [
            self._boolean_check(name, passed, required=required, detail=detail)
            for name, passed, required, detail in checks
        ]
    
    def _path_check(self, name: str, path: Path, required: bool) -> Dict[str, Any]:
        exists = path.exists()
        return {
            "name": name,
            "path": str(path),
            "required": required,
            "exists": exists,
            "passed": exists if required else True,
        }
    
    @staticmethod
    def _boolean_check(
        name: str,
        passed: bool,
        *,
        required: bool,
        detail: str,
    ) -> Dict[str, Any]:
        """Check boolean."""
        return {
            "name": name,
            "path": "",
            "required": required,
            "exists": passed,
            "passed": passed if required else True,
            "detail": detail,
        }

    @staticmethod
    def _markdown_has_minimum_sections(path: Path, min_headings: int = 1) -> bool:
        """Check markdown minimum sections."""
        if not path.exists() or not path.is_file():
            return False
        
        text = path.read_text(encoding="utf-8", errors="replace")
        heading_count = sum(1 for line in text.splitlines() if line.strip().startswith("#"))
        return heading_count >= min_headings
    
    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
