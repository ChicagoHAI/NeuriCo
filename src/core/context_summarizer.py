"""
Context Summarizer - Summarize phase handoff for long-running research agents.

The summarizer turns full workspace artifacts into decision-focused handoff summaries.
This prevents later agents from relying on huge logs or re-discovering context that
was already established.

Files managed:
- .neurico/phase_summary.json
  Latest summary for backward compatibility.

- .neurico/phase_summary_<stage>.json
  Stage-specific summaries, preserving resource-finder and experiment-runner handoffs seperately

The full discovered artifact set remains in the workspace. 
Only the most useful ocntext is forwarded through summary fields.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import re
from core.security import sanitize_text

RESOURCE_CANDIDATE_TYPES = {
    "paper",
    "dataset",
    "code",
    "baseline",
    "benchmark",
    "method",
    "experiment_direction",
}

class ContextSummarizer:
    """
    Generate structured handoff summaries between pipeline stages.

    It is designed to:
    - preserve only decision_critical context across stages
    - keep the full discovered artifacts in the workspace
    - pass only compressed summaries and top-k directions forward
    - keep constraints and failures separate from candidate recommendations
    """
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.neurico_dir / "phase_summary.json"
    
    def summarize_stage(self, stage_name: str, idea: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate and persist a summary for a completed stage.
        
        The summary is saved both as the latest summary and as a stage-specific artifact so 
        """
        if stage_name == "resource_finder":
            summary = self._summarize_resource_finder(idea)
        elif stage_name == "experiment_runner":
            summary = self._summarize_experiment_runner(idea)
        else:
            summary = {
                "stage": stage_name,
                "summary_text": f"No stage-specific summarizer for {stage_name}.",
                "key_findings": [],
                "decision_rationale": [],
                "constraints_and_failures": [],
                "next_steps": [],
                "top_k_candidates": [],
            }
        self._save_latest(summary)
        self._save_stage_specific(stage_name, summary)
        return summary

    def load_phase_summary(self) -> Optional[Dict[str, Any]]:
        """Load the latest phase summary."""
        if not self.summary_path.exists():
            return None
        with open(self.summary_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_stage_summary(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """Load stage-specific phase summary."""
        path = self._stage_summary_path(stage_name)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
               
    def _save_latest(self, summary: Dict[str, Any]) -> None:
        """Save the latest phase summary."""
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    
    def _save_stage_specific(self, stage_name: str, summary: Dict[str, Any]) -> None:
        """Save stage specific phase summary."""
        with open(self._stage_summary_path(stage_name), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    
    def _stage_summary_path(self, stage_name: str) -> Path:
        """Store stage specific summary path."""
        safe_stage = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stage_name).strip())
        if not safe_stage:
            safe_stage = "unknown"
        return self.neurico_dir / f"phase_summary_{safe_stage}.json"

    def _summarize_resource_finder(self, idea: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize resource finder."""
        literature_review = self._read_text(self.work_dir / "literature_review.md")
        resources_md = self._read_text(self.work_dir / "resources.md")
        top_k_candidates = self._derive_top_k_candidates(resources_md, idea, k=5)
        key_findings: List[str] = []
        decision_rationale: List[str] = []
        constraints_and_failures: List[str] = []
        if literature_review:
            key_findings.append("Literature review generated.")
        else:
            constraints_and_failures.append("Literature review missing or empty.")
        
        if resources_md:
            key_findings.append("Resources catalog generated.")
        else:
            constraints_and_failures.append("Resources catalog missing or empty.")
        
        if (self.work_dir / "papers").exists():
            key_findings.append("Paper directory available.")
        
        if (self.work_dir / "datasets").exists():
            key_findings.append("Dataset directory available.")
        
        if (self.work_dir / "code").exists():
            key_findings.append("Code directory available.")
        
        resource_failures = self._extract_resource_failures(resources_md)
        constraints_and_failures.extend(resource_failures)

        if top_k_candidates:
            decision_rationale.append("Top-K candidates selected to reduce exploration breadth in the next stage.")
        else:
            decision_rationale.append("No structured Top-K candidates could be extracted; next stage should rely on validated resources.")
        
        constraints_and_failures.extend(self._idea_constraints_as_text(idea))

        next_steps = [
            "Review gathered resources before implementation.",
            "Prioritize top-ranked resources for experiment design.",
            "Use only the most promising directions as primary context for the next stage.",
        ]

        summary_text = (
            "Resource finder completed. Resources were gathered, validated, "
            "and compressed into a prioritized handoff for experiment execution."
        )

        return self._sanitize_summary(
            {
                "stage": "resource_finder",
                "summary_text": summary_text,
                "key_findings": key_findings,
                "decision_rationale": decision_rationale,
                "constraints_and_failures": constraints_and_failures,
                "next_steps": next_steps,
                "top_k_candidates": top_k_candidates,
            }
        )
    
    def _summarize_experiment_runner(self, idea: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize experiment runner."""
        report = self._read_text(self.work_dir / "REPORT.md")
        planning = self._read_text(self.work_dir / "planning.md")
        readme = self._read_text(self.work_dir / "README.md")
        key_findings: List[str] = []
        decision_rationale: List[str] = []
        constraints_and_failures: List[str] = []

        if planning:
            key_findings.append("Planning artifacts generated.")
        else:
            constraints_and_failures.append("planning.md missing or empty.")
        
        if report:
            key_findings.append("Research report generated.")
        else:
            constraints_and_failures.append("REPORT.md missing or empty.")
        
        if readme:
            key_findings.append("Workspace README generated.")
        else:
            constraints_and_failures.append("README.md missing or empty.")
        
        if (self.work_dir / "results").exists():
            key_findings.append("Results directory available.")
        else:
            constraints_and_failures.append("results/ directory missing.")
        
        if (self.work_dir / "src").exists():
            key_findings.append("Source code directory available.")
        decision_rationale.append("Experimental artifacts were condensed into a final execution summary.")
        
        next_steps = [
            "Review final findings and reported limitations.",
            "Prepare final publication or paper-writing stage.",
        ]

        summary_text = (
            "Experiment runner completed. Experimental artifacts and documentation "
            "were produced and summarized for final review."
        )

        return self._sanitize_summary (
            {
                "stage": "experiment_runner",
                "summary_text": summary_text,
                "key_findings": key_findings,
                "decision_rationale": decision_rationale,
                "constraints_and_failures": constraints_and_failures,
                "next_steps": next_steps,
                "top_k_candidates": [],
            }
        )
    
    def _derive_top_k_candidates(
        self, 
        resources_text: str,
        idea: Optional[Dict[str, Any]],
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Rank resource candidates for the next stage.
        
        It narrows the next prompt to likely useful papers, datasets, codebases,
        baselines, benchmarks, methods, or concrete experiment directions.
        """

        if not resources_text.strip():
            return []
        
        candidates: List[Dict[str, Any]] = []
        for raw_line in resources_text.splitlines():
            line = raw_line.strip()
            if not (line.startswith("- ") or line.startswith("* ")):
                continue
            text = line[2:].strip()
            candidate_type = self._classify_candidate(text)
            if candidate_type is None:
                continue
            
            score = self._score_candidate(text, candidate_type, idea)
            if score <= 0:
                continue
            
            candidates.append(
                {
                    "text": sanitize_text(text),
                    "type": candidate_type,
                    "score": round(score, 4),                  
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:k]
    
    def _classify_candidate(self, text: str) -> Optional[str]:
        """Classify candidates."""
        lowered = text.lower()
        failure_terms = [
            "unavailable",
            "failed",
            "could not",
            "missing",
            "error",
            "fallback",
            "localhost",
            "permission denied",
        ]
        if any(term in lowered for term in failure_terms):
            return None
        
        if any(term in lowered for term in ["paper", "arxiv", "doi", "citation", "study"]):
            return "paper"
        
        if any(term in lowered for term in ["dataset", "benchmark data", "uci", "huggingface"]):
            return "dataset"

        if any(term in lowered for term in ["github", "repo", "code", "implementation"]):
            return "code"
        
        if "baseline" in lowered:
            return "baseline"
        
        if "benchmark" in lowered:
            return "benchmark"
        
        if any(term in lowered for term in ["method", "approach", "algorithm"]):
            return "method"       

        if any(term in lowered for term in ["experiment", "direction", "test", "compare"]):
            return "experiment_direction"
        
        return None
                   
    def _score_candidate(self, text: str, candidate_type: str, idea: Optional[Dict[str, Any]]) -> float:
        """
        Score a candidate by:
        - relevance
        - evidence strength
        - feasibility
        - idea alignment
        """
        lowered = text.lower()
        score = 0.0

        # relevance
        type_weights = {
            "dataset": 2.0,
            "baseline": 2.0,
            "benchmark": 1.75,
            "paper": 1.5,
            "code": 1.5,
            "method": 1.25,
            "experiment_direction": 1.25,
        }
        score += type_weights.get(candidate_type, 0.0)
        
        # evidence
        evidence_terms = ["influential", "state-of-the-art", "sota", "standard", "peer-reviewed"]
        score += sum(0.5 for term in evidence_terms if term in lowered)

        # feasibility
        feasibility_terms = ["lightweight", "small", "open-source", "available", "download"]
        score += sum(0.5 for term in feasibility_terms if term in lowered)

        # alignment
        if idea:
            idea_spec = idea.get("idea", {})
            hypothesis = str(idea_spec.get("hypothesis", "")).lower()
            constraints = idea_spec.get("constraints", {}) or {}
            methodology = idea_spec.get("methodology", {}) or {}

            for token in hypothesis.split():
                token = token.strip(".,;:()[]{}")
                if len(token) > 4 and token in lowered:
                    score += 0.2

            for baseline in methodology.get("baselines", []) or []:
                if str(baseline).lower() in lowered:
                    score += 0.75

            for metric in methodology.get("metrics", []) or []:
                if str(metric).lower() in lowered:
                    score += 0.5

            compute = str(constraints.get("compute", "")).lower()
            if compute == "cpu_only" and any(term in lowered for term in ["small", "lightweight", "efficient", "cpu"]):
                score += 0.5
        return score
    
    def _extract_resource_failures(self, resources_text: str) -> List[str]:
        """Extract known resource-gathering failures from resources.md."""
        failures: List[str] = []
        failure_terms = ["unavailable", "failed", "could not", "missing", "fallback"]

        for raw_line in resources_text.splitlines():
            line = raw_line.strip().lstrip("-* ").strip()
            lowered = line.lower()
            if any(term in lowered for term in failure_terms):
                failures.append(line)
        return failures[:5]
    
    def _idea_constraints_as_text(self, idea: Optional[Dict[str, Any]]) -> List[str]:
        """Extract relevant user constraints from the idea spec."""
        if not idea:
            return []
        
        idea_spec = idea.get("idea", {})
        constraints = idea_spec.get("constraints", {}) or {}

        result: List[str] = []
        compute = constraints.get("compute")
        time_limit = constraints.get("time_limit")
        budget = constraints.get("budget")

        if compute:
            result.append(f"Compute constraint: {compute}")
        if time_limit:
            result.append(f"Time limit: {time_limit} seconds")
        if budget is not None:
            result.append(f"Budget constraint: {budget}")
        return result

    def _sanitize_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize all user-visible summary text."""
        sanitized = dict(summary)
        for key in ["summary_text", "stage"]:
            sanitized[key] = sanitize_text(str(sanitized.get(key, "")))
        
        for key in ["key_findings", "decision_rationale", "constraints_and_failures", "next_steps"]:
            sanitized[key] = [sanitize_text(str(item)) for item in sanitized.get(key, [])]
        
        sanitized["top_k_candidates"] = [
            {
                "text": sanitize_text(str(candidate.get("text", ""))),
                "type": sanitize_text(str(candidate.get("type", "unknown"))),
                "score": candidate.get("score", 0),
            }
            for candidate in sanitized.get("top_k_candidates", [])
        ]
        return sanitized
    
    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        return sanitize_text(path.read_text(encoding="utf-8", errors="replace"))