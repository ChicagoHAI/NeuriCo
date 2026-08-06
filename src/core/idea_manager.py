"""
Idea Manager - Validates, stores, and tracks research ideas

This module handles the lifecycle of research ideas:
1. Validation against schema
2. Unique ID generation
3. Status tracking (submitted → in_progress → completed)
4. Storage and retrieval
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import yaml
import json
import hashlib
import re
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_loader import ConfigLoader
from core.local_resources import (
    collect_host_paths,
    validate_evaluation_spec,
    validate_local_resources,
)


def _check_mapping(value: Any, label: str, errors: List[str]) -> bool:
    """Record an error unless value is a mapping. Returns True when it is.

    Callers gate further inspection on the return value: every consumer of
    these blocks (prompt_generator, the agents) calls .get() on them, so a
    non-mapping is a crash waiting to happen rather than a cosmetic problem.
    """
    if not isinstance(value, dict):
        errors.append(f"{label} must be a mapping, got {type(value).__name__}")
        return False
    return True


def _check_string(value: Any, label: str, errors: List[str],
                  min_length: int = None, max_length: int = None) -> bool:
    """Record an error unless value is a string within the schema's bounds."""
    if not isinstance(value, str):
        errors.append(f"{label} must be a string, got {type(value).__name__}")
        return False
    if min_length is not None and len(value) < min_length:
        errors.append(f"{label} must be at least {min_length} characters "
                      f"(got {len(value)})")
        return False
    if max_length is not None and len(value) > max_length:
        errors.append(f"{label} must be at most {max_length} characters "
                      f"(got {len(value)})")
        return False
    return True


def _check_list(value: Any, label: str, errors: List[str],
                item_type: type = None, item_label: str = "item") -> bool:
    """Record an error unless value is a list, optionally of item_type."""
    if not isinstance(value, list):
        errors.append(f"{label} must be a list, got {type(value).__name__}")
        return False
    if item_type is not None:
        for idx, item in enumerate(value):
            if not isinstance(item, item_type):
                errors.append(
                    f"{label}[{idx}]: {item_label} must be "
                    f"{item_type.__name__}, got {type(item).__name__}")
                return False
    return True


def _validate_background(background: Any, errors: List[str],
                         warnings: List[str]) -> None:
    """Validate idea.background against the schema."""
    if not _check_mapping(background, "background", errors):
        return

    if 'description' in background:
        _check_string(background['description'], "background.description", errors)

    # papers: each entry needs a description plus either a url or a path
    if 'papers' in background and background['papers'] is not None:
        if _check_list(background['papers'], "background.papers", errors):
            for idx, paper in enumerate(background['papers']):
                label = f"background.papers[{idx}]"
                if not _check_mapping(paper, label, errors):
                    continue
                if 'url' not in paper and 'path' not in paper:
                    errors.append(f"{label}: must provide either 'url' or 'path'")
                if 'description' not in paper:
                    errors.append(f"{label}: missing required field 'description'")

    if 'datasets' in background and background['datasets'] is not None:
        if _check_list(background['datasets'], "background.datasets", errors):
            for idx, dataset in enumerate(background['datasets']):
                label = f"background.datasets[{idx}]"
                if not _check_mapping(dataset, label, errors):
                    continue
                for field in ('name', 'source'):
                    if field not in dataset:
                        errors.append(f"{label}: missing required field '{field}'")

    if 'code_references' in background and background['code_references'] is not None:
        if _check_list(background['code_references'], "background.code_references", errors):
            for idx, ref in enumerate(background['code_references']):
                label = f"background.code_references[{idx}]"
                if not _check_mapping(ref, label, errors):
                    continue
                for field in ('repo', 'description'):
                    if field not in ref:
                        errors.append(f"{label}: missing required field '{field}'")


def _validate_methodology(methodology: Any, errors: List[str]) -> None:
    """Validate idea.methodology against the schema."""
    if not _check_mapping(methodology, "methodology", errors):
        return

    if 'approach' in methodology:
        _check_string(methodology['approach'], "methodology.approach", errors)

    for field in ('steps', 'baselines', 'metrics'):
        if field in methodology and methodology[field] is not None:
            _check_list(methodology[field], f"methodology.{field}", errors,
                        item_type=str, item_label="entry")


def _validate_constraints(constraints: Any, errors: List[str],
                          warnings: List[str]) -> None:
    """Validate idea.constraints against the schema."""
    if not _check_mapping(constraints, "constraints", errors):
        return

    if 'compute' in constraints:
        valid_compute = ['cpu_only', 'gpu_required', 'multi_gpu', 'tpu', 'any']
        if constraints['compute'] not in valid_compute:
            errors.append(f"Invalid compute constraint: {constraints['compute']}")

    if 'time_limit' in constraints:
        # Range stays advisory: an out-of-range limit is a judgement call, not
        # a structural fault, and nothing downstream breaks on it.
        if not isinstance(constraints['time_limit'], int) or \
                isinstance(constraints['time_limit'], bool):
            errors.append("time_limit must be an integer (seconds)")
        elif constraints['time_limit'] < 60:
            warnings.append("time_limit is very short (< 60 seconds)")
        elif constraints['time_limit'] > 86400:
            warnings.append("time_limit is very long (> 24 hours)")

    if 'memory' in constraints:
        if _check_string(constraints['memory'], "constraints.memory", errors):
            if not re.fullmatch(r'[0-9]+(GB|MB)', constraints['memory']):
                errors.append(
                    f"constraints.memory must look like '8GB' or '512MB', "
                    f"got {constraints['memory']!r}")

    if 'budget' in constraints:
        budget = constraints['budget']
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            errors.append(
                f"constraints.budget must be a number, got {type(budget).__name__}")
        elif budget < 0:
            errors.append("constraints.budget must not be negative")

    if 'dependencies' in constraints and constraints['dependencies'] is not None:
        _check_list(constraints['dependencies'], "constraints.dependencies",
                    errors, item_type=str, item_label="dependency")


def _validate_metadata(metadata: Any, errors: List[str]) -> None:
    """Validate idea.metadata against the schema."""
    if not _check_mapping(metadata, "metadata", errors):
        return

    for field in ('author', 'source', 'source_url', 'estimated_duration'):
        if field in metadata and metadata[field] is not None:
            _check_string(metadata[field], f"metadata.{field}", errors)

    for field in ('tags', 'related_ideas'):
        if field in metadata and metadata[field] is not None:
            _check_list(metadata[field], f"metadata.{field}", errors,
                        item_type=str, item_label="entry")

    if 'priority' in metadata:
        valid_priorities = ['low', 'medium', 'high', 'urgent']
        if metadata['priority'] not in valid_priorities:
            errors.append(
                f"Invalid metadata.priority: {metadata['priority']}. "
                f"Must be one of: {', '.join(valid_priorities)}")


def _validate_expected_outputs(expected_outputs: Any, errors: List[str],
                               warnings: List[str]) -> None:
    """Validate idea.expected_outputs against the schema."""
    if not _check_list(expected_outputs, "expected_outputs", errors):
        return

    if not expected_outputs:
        warnings.append("expected_outputs is empty - agent will determine appropriate outputs")
        return

    # The schema lists an enum, but output types are open-ended in practice:
    # the shipped math/Lean examples declare 'proof' and
    # 'computational_verification', and domains keep inventing their own. So
    # an unrecognized type warns rather than fails -- the same treatment
    # unknown domains already get. Structure (mapping, type, format) stays a
    # hard requirement, since that is what consumers actually index into.
    known_types = ['metrics', 'visualization', 'model', 'dataset', 'report',
                   'code', 'analysis']
    for idx, output in enumerate(expected_outputs):
        if not _check_mapping(output, f"Output {idx}", errors):
            continue
        if 'type' not in output:
            errors.append(f"Output {idx}: missing 'type' field")
        elif output['type'] not in known_types:
            warnings.append(f"Output {idx}: unrecognized type "
                            f"{output['type']!r} (known types: "
                            f"{', '.join(known_types)})")
        if 'format' not in output:
            errors.append(f"Output {idx}: missing 'format' field")


def validate_idea_spec(idea_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate an idea specification against the NeuriCo schema.

    Module-level so callers that only need validation (e.g. the IdeaHub
    converter, which validates before anything is written) can reach it
    without constructing an IdeaManager -- whose __init__ creates the
    submitted/in_progress/completed directories as a side effect.

    Args:
        idea_spec: Idea specification dictionary

    Returns:
        Dictionary with keys:
        - 'valid': bool
        - 'errors': List of error messages
        - 'warnings': List of warning messages
    """
    errors = []
    warnings = []

    # Check top-level structure
    if not isinstance(idea_spec, dict) or 'idea' not in idea_spec:
        errors.append("Missing top-level 'idea' key")
        return {'valid': False, 'errors': errors, 'warnings': warnings}

    idea = idea_spec['idea']

    # Every check below indexes into `idea`; a non-mapping here would turn
    # membership tests into substring tests (or raise), so stop now.
    if not _check_mapping(idea, "idea", errors):
        return {'valid': False, 'errors': errors, 'warnings': warnings}

    # Required fields (v1.1 - reduced from v1.0)
    required_fields = ['title', 'domain', 'hypothesis']
    for field in required_fields:
        if field not in idea or not idea[field]:
            errors.append(f"Missing required field: {field}")

    # Required-field types and lengths, per ideas/schema.yaml. Only checked
    # when present and non-empty; absence is already an error above.
    if idea.get('title'):
        _check_string(idea['title'], "title", errors, min_length=10, max_length=200)
    if idea.get('hypothesis'):
        _check_string(idea['hypothesis'], "hypothesis", errors, min_length=20)

    # Validate domain
    domain_is_string = True
    if idea.get('domain'):
        domain_is_string = _check_string(idea['domain'], "domain", errors)

    config_loader = ConfigLoader()
    valid_domains = config_loader.get_valid_domains()
    allow_unknown = config_loader.should_allow_unknown_domains()

    if domain_is_string and 'domain' in idea and idea['domain'] not in valid_domains:
        if allow_unknown:
            default_domain = config_loader.get_default_domain()
            warnings.append(
                f"Unknown domain '{idea['domain']}' will be treated as '{default_domain}'. "
                f"Valid domains: {', '.join(valid_domains)}"
            )
        else:
            errors.append(
                f"Invalid domain: {idea['domain']}. "
                f"Must be one of: {', '.join(valid_domains)}"
            )

    if 'max_directions' in idea:
        max_directions = idea['max_directions']
        if not isinstance(max_directions, int) or isinstance(max_directions, bool):
            errors.append("max_directions must be an integer")
        elif not 1 <= max_directions <= 10:
            errors.append("max_directions must be between 1 and 10")

    if 'comments' in idea and idea['comments'] is not None:
        _check_string(idea['comments'], "comments", errors)

    # Optional structured blocks. Each is a mapping or list downstream
    # (prompt_generator and the agents call .get()/iterate on them), so a
    # wrong type here becomes a crash mid-run rather than a bad prompt.
    #
    # An explicit null is treated as absent rather than as a type error:
    # `constraints:` with nothing under it is ordinary YAML for "no
    # constraints", and every consumer guards with `if constraints:`, so None
    # is skipped safely. A *string* like `constraints: none` is not -- that
    # reaches constraints.get('compute') and raises. Hence the isinstance
    # checks below rather than a truthiness test.
    if 'background' in idea and idea['background'] is not None:
        _validate_background(idea['background'], errors, warnings)

    if 'methodology' in idea and idea['methodology'] is not None:
        _validate_methodology(idea['methodology'], errors)

    if 'constraints' in idea and idea['constraints'] is not None:
        _validate_constraints(idea['constraints'], errors, warnings)

    if 'metadata' in idea and idea['metadata'] is not None:
        _validate_metadata(idea['metadata'], errors)

    # Validate expected outputs (optional in v1.1)
    if 'expected_outputs' in idea and idea['expected_outputs'] is not None:
        _validate_expected_outputs(idea['expected_outputs'], errors, warnings)
    else:
        warnings.append("No expected_outputs specified - agent will determine appropriate outputs based on research type")

    # Validate evaluation criteria
    if 'evaluation_criteria' in idea and idea['evaluation_criteria'] is not None:
        if _check_list(idea['evaluation_criteria'], "evaluation_criteria",
                       errors, item_type=str, item_label="criterion"):
            if len(idea['evaluation_criteria']) == 0:
                warnings.append("No evaluation criteria specified")

    # Validate local resources (contractual: path + usage required,
    # missing paths are warnings until staging)
    lr_errors, lr_warnings = validate_local_resources(idea)
    errors.extend(lr_errors)
    warnings.extend(lr_warnings)

    # Validate structured evaluation spec
    ev_errors, ev_warnings = validate_evaluation_spec(idea)
    errors.extend(ev_errors)
    warnings.extend(ev_warnings)

    valid = len(errors) == 0

    return {
        'valid': valid,
        'errors': errors,
        'warnings': warnings
    }


def resolve_ideas_dir(project_root: Optional[Path] = None) -> Path:
    """Resolve the ideas directory, honoring the NEURICO_IDEAS override.

    Mirrors NEURICO_WORKSPACE: if NEURICO_IDEAS is set, use it, so a shared
    read-only install can point each user at their own ideas directory.
    Otherwise fall back to <project_root>/ideas (project_root defaults to the
    repo root), which is the historical behavior.
    """
    env_ideas = os.getenv("NEURICO_IDEAS")
    if env_ideas:
        return Path(env_ideas)
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent
    return Path(project_root) / "ideas"


class IdeaManager:
    """
    Manages research idea submissions and tracking.

    Handles validation, storage, and status updates for research ideas.
    """

    def __init__(self, ideas_dir: Optional[Path] = None):
        """
        Initialize idea manager.

        Args:
            ideas_dir: Root directory for idea storage.
                      Defaults to project_root/ideas/
        """
        if ideas_dir is None:
            # Assume we're in src/core/, go up to project root
            project_root = Path(__file__).parent.parent.parent
            ideas_dir = project_root / "ideas"

        self.ideas_dir = Path(ideas_dir)
        self.submitted_dir = self.ideas_dir / "submitted"
        self.in_progress_dir = self.ideas_dir / "in_progress"
        self.completed_dir = self.ideas_dir / "completed"
        self.schema_path = self.ideas_dir / "schema.yaml"

        # Ensure directories exist
        for dir_path in [self.submitted_dir, self.in_progress_dir,
                         self.completed_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def get_idea_path(self, idea_id: str) -> Path:
        """Return the current file path for an idea, searching all status directories."""
        for directory in [self.submitted_dir, self.in_progress_dir, self.completed_dir]:
            idea_path = directory / f"{idea_id}.yaml"
            if idea_path.exists():
                return idea_path
        raise FileNotFoundError(f"Idea file not found for: {idea_id}")

    def submit_idea(self, idea_spec: Dict[str, Any],
                   validate: bool = True) -> str:
        """
        Submit a new research idea.

        Args:
            idea_spec: Idea specification dictionary
            validate: Whether to validate against schema (default True)

        Returns:
            idea_id: Unique identifier for the idea

        Raises:
            ValueError: If validation fails
        """
        if validate:
            validation_result = self.validate_idea(idea_spec)
            if not validation_result['valid']:
                errors = "\n".join(validation_result['errors'])
                raise ValueError(f"Idea validation failed:\n{errors}")

        # Generate unique ID
        idea_id = self._generate_idea_id(idea_spec)

        # Add metadata
        if 'metadata' not in idea_spec.get('idea', {}):
            idea_spec['idea']['metadata'] = {}

        idea_spec['idea']['metadata']['idea_id'] = idea_id
        idea_spec['idea']['metadata']['created_at'] = datetime.now().isoformat()
        idea_spec['idea']['metadata']['status'] = 'submitted'

        # Save to submitted directory
        idea_path = self.submitted_dir / f"{idea_id}.yaml"
        with open(idea_path, 'w', encoding='utf-8') as f:
            yaml.dump(idea_spec, f, default_flow_style=False, sort_keys=False)

        # Sidecar for docker/run.sh: host paths this idea depends on, one per
        # line, so cmd_run can mount them (bash cannot parse the idea YAML)
        host_paths = collect_host_paths(idea_spec.get('idea', {}))
        if host_paths:
            mounts_dir = self.ideas_dir / "mounts"
            mounts_dir.mkdir(parents=True, exist_ok=True)
            (mounts_dir / f"{idea_id}.txt").write_text(
                "\n".join(host_paths) + "\n", encoding='utf-8')
            print(f"  Local paths recorded for docker mounts: {len(host_paths)}")

        print(f"✓ Idea submitted successfully: {idea_id}")
        print(f"  Title: {idea_spec['idea'].get('title', 'Untitled')}")
        print(f"  Location: {idea_path}")

        return idea_id

    def validate_idea(self, idea_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate idea specification.

        Delegates to the module-level validate_idea_spec() so the converter
        and the submit path enforce exactly the same rules.

        Args:
            idea_spec: Idea specification dictionary

        Returns:
            Dictionary with keys:
            - 'valid': bool
            - 'errors': List of error messages
            - 'warnings': List of warning messages
        """
        return validate_idea_spec(idea_spec)

    def get_idea(self, idea_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve idea by ID.

        Searches all status directories for the idea.

        Args:
            idea_id: Unique idea identifier

        Returns:
            Idea specification dictionary, or None if not found
        """
        # Search all directories
        for directory in [self.submitted_dir, self.in_progress_dir,
                         self.completed_dir]:
            idea_path = directory / f"{idea_id}.yaml"
            if idea_path.exists():
                with open(idea_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)

        return None

    def update_status(self, idea_id: str, new_status: str) -> bool:
        """
        Update idea status and move to appropriate directory.

        Args:
            idea_id: Unique idea identifier
            new_status: New status (submitted, in_progress, completed)

        Returns:
            True if successful, False if idea not found

        Raises:
            ValueError: If status is invalid
        """
        valid_statuses = ['submitted', 'in_progress', 'completed']
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}. "
                           f"Must be one of: {', '.join(valid_statuses)}")

        # Find current location
        current_path = None
        for directory in [self.submitted_dir, self.in_progress_dir,
                         self.completed_dir]:
            candidate_path = directory / f"{idea_id}.yaml"
            if candidate_path.exists():
                current_path = candidate_path
                break

        if current_path is None:
            return False  # Idea not found

        # Load idea
        with open(current_path, 'r', encoding='utf-8') as f:
            idea_spec = yaml.safe_load(f)

        # Update status in metadata
        if 'metadata' not in idea_spec['idea']:
            idea_spec['idea']['metadata'] = {}
        idea_spec['idea']['metadata']['status'] = new_status
        idea_spec['idea']['metadata']['updated_at'] = datetime.now().isoformat()

        # Determine new location
        status_to_dir = {
            'submitted': self.submitted_dir,
            'in_progress': self.in_progress_dir,
            'completed': self.completed_dir
        }
        new_dir = status_to_dir[new_status]
        new_path = new_dir / f"{idea_id}.yaml"

        # Save to new location
        with open(new_path, 'w', encoding='utf-8') as f:
            yaml.dump(idea_spec, f, default_flow_style=False, sort_keys=False)

        # Remove from old location (if different)
        if new_path != current_path:
            current_path.unlink()

        print(f"✓ Updated idea {idea_id} status: {new_status}")

        return True

    def list_ideas(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all ideas, optionally filtered by status.

        Args:
            status: Filter by status (submitted, in_progress, completed)
                   If None, returns all ideas.

        Returns:
            List of idea summaries (not full specifications)
        """
        ideas = []

        # Determine which directories to search
        if status is None:
            directories = [self.submitted_dir, self.in_progress_dir,
                          self.completed_dir]
        elif status == 'submitted':
            directories = [self.submitted_dir]
        elif status == 'in_progress':
            directories = [self.in_progress_dir]
        elif status == 'completed':
            directories = [self.completed_dir]
        else:
            raise ValueError(f"Invalid status: {status}")

        # Collect ideas
        for directory in directories:
            for idea_path in directory.glob("*.yaml"):
                with open(idea_path, 'r', encoding='utf-8') as f:
                    idea_spec = yaml.safe_load(f)

                # Extract summary
                idea = idea_spec.get('idea', {})
                metadata = idea.get('metadata', {})

                summary = {
                    'idea_id': metadata.get('idea_id', idea_path.stem),
                    'title': idea.get('title', 'Untitled'),
                    'domain': idea.get('domain', 'unknown'),
                    'status': metadata.get('status', 'unknown'),
                    'created_at': metadata.get('created_at', 'unknown'),
                    'path': str(idea_path)
                }

                ideas.append(summary)

        # Sort by creation time (most recent first)
        ideas.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return ideas

    def _generate_idea_id(self, idea_spec: Dict[str, Any]) -> str:
        """
        Generate a unique ID for an idea.

        Uses a combination of timestamp and title hash for uniqueness.

        Args:
            idea_spec: Idea specification

        Returns:
            Unique idea ID string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = idea_spec.get('idea', {}).get('title', 'untitled')

        # Create a short hash of the title
        title_hash = hashlib.md5(title.encode()).hexdigest()[:8]

        # Sanitize title for use in ID
        safe_title = title.lower()
        safe_title = ''.join(c if c.isalnum() or c.isspace() else '_'
                            for c in safe_title)
        safe_title = '_'.join(safe_title.split())[:30]  # Max 30 chars

        idea_id = f"{safe_title}_{timestamp}_{title_hash}"

        return idea_id


def main():
    """Test the idea manager."""
    manager = IdeaManager()

    # Example idea
    example_idea = {
        'idea': {
            'title': 'Test ML Experiment',
            'domain': 'machine_learning',
            'hypothesis': 'This is a test hypothesis for validation',
            'expected_outputs': [
                {
                    'type': 'metrics',
                    'format': 'json',
                    'fields': ['accuracy']
                }
            ],
            'evaluation_criteria': [
                'Test criterion'
            ]
        }
    }

    # Validate
    print("Validating idea...")
    result = manager.validate_idea(example_idea)
    print(f"Valid: {result['valid']}")
    if result['errors']:
        print(f"Errors: {result['errors']}")
    if result['warnings']:
        print(f"Warnings: {result['warnings']}")

    # Submit
    if result['valid']:
        print("\nSubmitting idea...")
        idea_id = manager.submit_idea(example_idea)

        # Retrieve
        print("\nRetrieving idea...")
        retrieved = manager.get_idea(idea_id)
        print(f"Retrieved title: {retrieved['idea']['title']}")

        # List
        print("\nListing all ideas:")
        all_ideas = manager.list_ideas()
        for idea in all_ideas:
            print(f"  - {idea['idea_id']}: {idea['title']} [{idea['status']}]")


if __name__ == "__main__":
    main()
