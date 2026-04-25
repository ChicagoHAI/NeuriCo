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
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_loader import ConfigLoader


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

        print(f"✓ Idea submitted successfully: {idea_id}")
        print(f"  Title: {idea_spec['idea'].get('title', 'Untitled')}")
        print(f"  Location: {idea_path}")

        return idea_id

    def validate_idea(self, idea_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate idea specification.

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
        if 'idea' not in idea_spec:
            errors.append("Missing top-level 'idea' key")
            return {'valid': False, 'errors': errors, 'warnings': warnings}

        idea = idea_spec['idea']

        # Required fields (v1.1 - reduced from v1.0)
        required_fields = ['title', 'domain', 'hypothesis']
        for field in required_fields:
            if field not in idea or not idea[field]:
                errors.append(f"Missing required field: {field}")

        # Validate domain
        config_loader = ConfigLoader()
        valid_domains = config_loader.get_valid_domains()
        allow_unknown = config_loader.should_allow_unknown_domains()

        if 'domain' in idea and idea['domain'] not in valid_domains:
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

        # Validate hypothesis length
        if 'hypothesis' in idea and len(idea['hypothesis']) < 20:
            warnings.append("Hypothesis is very short (< 20 characters). "
                          "Consider providing more detail.")

        # Validate expected outputs (optional in v1.1)
        if 'expected_outputs' in idea:
            if not isinstance(idea['expected_outputs'], list):
                errors.append("expected_outputs must be a list")
            elif len(idea['expected_outputs']) == 0:
                warnings.append("expected_outputs is empty - agent will determine appropriate outputs")
            else:
                for idx, output in enumerate(idea['expected_outputs']):
                    if 'type' not in output:
                        errors.append(f"Output {idx}: missing 'type' field")
                    if 'format' not in output:
                        errors.append(f"Output {idx}: missing 'format' field")
        else:
            warnings.append("No expected_outputs specified - agent will determine appropriate outputs based on research type")

        # Validate constraints
        if 'constraints' in idea:
            constraints = idea['constraints']

            if 'compute' in constraints:
                valid_compute = ['cpu_only', 'gpu_required', 'multi_gpu', 'tpu', 'any']
                if constraints['compute'] not in valid_compute:
                    errors.append(f"Invalid compute constraint: {constraints['compute']}")

            if 'time_limit' in constraints:
                if not isinstance(constraints['time_limit'], int):
                    errors.append("time_limit must be an integer (seconds)")
                elif constraints['time_limit'] < 60:
                    warnings.append("time_limit is very short (< 60 seconds)")
                elif constraints['time_limit'] > 86400:
                    warnings.append("time_limit is very long (> 24 hours)")

        # Validate evaluation criteria
        if 'evaluation_criteria' in idea:
            if not isinstance(idea['evaluation_criteria'], list):
                errors.append("evaluation_criteria must be a list")
            elif len(idea['evaluation_criteria']) == 0:
                warnings.append("No evaluation criteria specified")

        valid = len(errors) == 0

        return {
            'valid': valid,
            'errors': errors,
            'warnings': warnings
        }

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
