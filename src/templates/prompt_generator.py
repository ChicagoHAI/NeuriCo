"""
Prompt Generator - Combines templates with idea specifications

This module generates complete prompts for research agents by:
1. Loading template files (base + domain-specific)
2. Rendering templates with idea-specific variables
3. Composing multi-layer prompts
4. Injecting stateful handoff context for long-running execution

Context-management support:
- phase_summary: compact summary from prior pipeline stage
- state_snapshot: current STATE.md machine-readable snapshot
- top-k candidate rendering for focused downstream execution

The PromptGenerator formats context.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config_loader import ConfigLoader, normalize_domain
from core.security import sanitize_text


class PromptGenerator:
    """
    Generates research prompts from templates and idea specifications.

    Uses Jinja2 templating to inject idea-specific content into
    structured prompt templates.

    Domain-specific agent templates override default templates when present.
    """

    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize prompt generator.

        Args:
            template_dir: Root directory containing template files.
                         Defaults to project_root/templates/
        """
        if template_dir is None:
            # Assume we're in src/templates/, go up to project root
            project_root = Path(__file__).parent.parent.parent
            template_dir = project_root / "templates"

        self.template_dir = Path(template_dir)

        # Set up Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Add custom filters
        self.env.filters['upper'] = str.upper
        self.env.filters['lower'] = str.lower
        self.env.filters['title'] = str.title

    def _load_template_with_domain_override(self, template_path: str, domain: str) -> str:
        """
        Load a template file, checking for a domain-specific override first.

        Looks for templates/domains/{domain}/{filename} before falling
        back to the universal template at template_path. Override only activates
        if the override file physically exists.

        Args:
            template_path: Path relative to template_dir (e.g. 'agents/resource_finder.txt')
            domain: Domain name (e.g. 'mathematics')

        Returns:
            Template content as string
        """
        normalized_domain = normalize_domain(domain or "general")
        filename = Path(template_path).name
        override_path = f"domains/{normalized_domain}/{filename}"

        try:
            return self.load_template(override_path)
        except FileNotFoundError:
            return self.load_template(template_path)

    def load_template(self, template_path: str) -> str:
        """
        Load a template file as plain text.

        Args:
            template_path: Path relative to template_dir

        Returns:
            Template content as string
        """
        full_path = self.template_dir / template_path

        if not full_path.exists():
            raise FileNotFoundError(f"Template not found: {full_path}")

        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()

    def render_template(self, template_content: str, variables: Dict[str, Any]) -> str:
        """
        Render a template string with variables.

        Args:
            template_content: Template string (may contain Jinja2 syntax)
            variables: Dictionary of variables to inject

        Returns:
            Rendered template string
        """
        template = self.env.from_string(template_content)
        return template.render(**variables)

    def generate_research_prompt(self, idea: Dict[str, Any],
                                 root_dir: Optional[Path] = None) -> str:
        """
        Generate the main research prompt from an idea specification.

        This composes:
        1. Base researcher template
        2. Domain-specific template
        3. Idea-specific content (hypothesis, constraints, etc.)

        Args:
            idea: Idea specification (parsed from YAML)
            root_dir: Root directory for the research project (for paths)

        Returns:
            Complete research prompt string
        """
        # Extract idea details
        idea_spec = idea.get('idea', {})

        # Load base researcher template
        base_template = self.load_template('base/researcher.txt')

        # Load domain-specific template with intelligent fallback
        config_loader = ConfigLoader()
        domain = idea_spec.get('domain', 'machine_learning')

        # Normalize domain (falls back to default if unknown)
        normalized_domain = normalize_domain(domain)

        if domain != normalized_domain:
            print(f"ℹ️  Domain '{domain}' not recognized, using '{normalized_domain}' template")

        # Try to load domain template
        domain_template = ""
        domain_template_path = f'domains/{normalized_domain}/core.txt'

        try:
            domain_template = self.load_template(domain_template_path)
        except FileNotFoundError:
            # If no specific template exists, try the default domain
            default_domain = config_loader.get_default_domain()
            default_template_path = f'domains/{default_domain}/core.txt'

            print(f"ℹ️  No template for '{normalized_domain}', using '{default_domain}' template")

            try:
                domain_template = self.load_template(default_template_path)
            except FileNotFoundError:
                # Ultimate fallback: no domain-specific guidance
                print(f"⚠️  No domain templates available, using base template only")
                domain_template = ""

        # Prepare variables for template rendering
        variables = self._prepare_variables(idea_spec, root_dir)

        # Compose the full prompt
        prompt_parts = [
            "=" * 80,
            "                    RESEARCH TASK SPECIFICATION",
            "=" * 80,
            "",
            self._generate_task_section(idea_spec),
            "",
            "=" * 80,
            "                 RESEARCH METHODOLOGY (UNIVERSAL)",
            "=" * 80,
            "",
            base_template,
            ""
        ]

        if domain_template:
            prompt_parts.extend([
                "=" * 80,
                f"           DOMAIN-SPECIFIC GUIDELINES: {domain.upper().replace('_', ' ')}",
                "=" * 80,
                "",
                domain_template,
                ""
            ])

        # Join all parts
        full_prompt = "\n".join(prompt_parts)

        # Render with variables (in case templates use Jinja2 syntax)
        rendered_prompt = self.render_template(full_prompt, variables)

        return rendered_prompt
    
    def _prepare_variables(
            self,
            idea_spec: Dict[str, Any],
            root_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Prepare variables dictionary for template rendering.

        Args:
            idea_spec: inner idea specification.
            root_dir: workspace root directory.
        
        Returns:
            dictionary of template variables.
        """
        if root_dir is None:
            root_dir = Path.cwd()
        
        return {
            "idea": idea_spec,
            "root_dir": str(root_dir),
            "title": idea_spec.get("title", "Untitled Research"),
            "domain": idea_spec.get("domain", "unknown"),
            "hypothesis": idea_spec.get("hypothesis", "No hypothesis specified"),
            "constraints": idea_spec.get("constraints", {}),
            "expected_outputs": idea_spec.get("expected_outputs", []),
            "evaluation_criteria": idea_spec.get("evaluation_criteria", []),
            "background": idea_spec.get("background", {}),
            "methodology": idea_spec.get("methodology", {}),
        }
    
    def _generate_task_section(self, idea_spec: Dict[str, Any]) -> str:
        """
        Generate the task-specific section of the prompt.

        This section contains the research title, domain, hypothesis, 
        background, methodology, constraints, expected outputs, and success
        criteria supplied by the user.
        """
        lines: List[str] = []
        title = idea_spec.get("title", "Untitled Research")
        lines.append(f"## RESEARCH TITLE\n\n{title}\n")

        domain = idea_spec.get("domain", "unknown")
        lines.append(f"## RESEARCH DOMAIN\n\n{domain.replace('_', ' ').title()}\n")

        hypothesis = idea_spec.get("hypothesis", "No hypothesis is specified")
        lines.append(f"## HYPOTHESIS / RESEARCH QUESTION\n\n{hypothesis}\n")
        
        background = idea_spec.get("background", {})
        if background:
            lines.append("## BACKGROUND\n")
            if background.get("description"):
                lines.append("### User-Provided Instructions and Context:\n")
                lines.append(f">>> {background['description']} <<<\n")
                lines.append("(Note: Follow any specific instructions above with high priority)\n")
            
            if background.get("papers"):
                lines.append("### Relevant Papers:\n")
                for paper in background["papers"]:
                    if isinstance(paper, dict):
                        if "url" in paper:
                            lines.append(f"- [{paper.get('description', 'Paper')}]({paper['url']})")
                        elif "path" in paper:
                            lines.append(f"- [{paper.get('description', 'Paper')}]({paper['path']})")
                        else:
                            lines.append(f"- {paper.get('description', paper)}")
                    else:
                        lines.append(f"- {paper}")
                lines.append("")

            if background.get("datasets"):
                lines.append("### Datasets:\n")
                for dataset in background["datasets"]:
                    if isinstance(dataset, dict):
                        name = dataset.get("name", "Unknown")
                        source = dataset.get("source", "Unknown source")
                        desc = dataset.get("description", "")
                        lines.append(f"- **{name}**: {source}")
                        if desc:
                            lines.append(f" {desc}")
                    else:
                        lines.append(f"- {dataset}")
                lines.append("")
            if background.get("code_references"):
                lines.append("### Code References:\n")
                lines.append(
                    "**IMPORTANT**: The following repositories are specifically mentioned and must be downloaded and explored:\n"
                )
                for repo in background["code_references"]:
                    if isinstance(repo, dict):
                        repo_url = repo.get("repo", repo.get("url", ""))
                        desc = repo.get("description", "Code repository")
                        lines.append(f"- **{desc}**")
                        lines.append(f"   - URL: {repo_url}")
                        lines.append("   - ACTION REQUIRED: Clone this repository and explore its capability")
                    else:
                        lines.append(f"- {repo}")
                lines.append("")
            
        methodology = idea_spec.get("methodology", {})
        if methodology:
            lines.append("## PROPOSED METHODOLOGY\n")
            if methodology.get("approach"):
                lines.append(f"**Approach**: {methodology['approach']}\n")
            
            if methodology.get("steps"):
                lines.append("**Steps**:")
                for i, step in enumerate(methodology["steps"], 1):
                    lines.append(f"{i}. {step}")
                lines.append("")
            
            if methodology.get("baselines"):
                lines.append(f"**Baselines**: {'. '.join(map(str, methodology['baselines']))}\n")

            if methodology.get("metrics"):
                lines.append(f"**Evaluation Metrics**: {'. '.join(map(str, methodology['metrics']))}\n")
        
        constraints = idea_spec.get("constraints", {})
        if constraints:
            lines.append("## CONSTRAINTS\n")

            compute = constraints.get("compute", "any")
            lines.append(f"- **Compute**: {compute}")

            time_limit = constraints.get("time_limit", 3600)
            try:
                time_limit_int = int(time_limit)
                hours = time_limit_int // 3600
                minutes = (time_limit_int % 3600) // 60
                time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                lines.append(f"- **Time Limit**: {time_str} ({time_limit_int} seconds)")
            except (TypeError, ValueError):
                lines.append(f"- **Time Limit**: {time_limit}")
            
            if "memory" in constraints:
                lines.append(f"- **Memory**: {constraints['memory']}")
            
            if "budget" in constraints:
                budget = constraints["budget"]
                if isinstance(budget, (int, float)):
                    lines.append(f"- **Budget**: ${budget:.2f}")
                else:
                    lines.append(f"- **Budget**: {budget}")
            if constraints.get("dependencies"):
                lines.append(f"- **Dependencies**: {', '.join(map(str, constraints['dependencies']))}")
            lines.append("")
        expected_outputs = idea_spec.get("expected_outputs", [])
        if expected_outputs:
            lines.append("## EXPECTED OUTPUTS\n")
            lines.append("Your research MUST produce the following outputs:\n")

            for output in expected_outputs:
                output_type = output.get("type", "unknown")
                format_spec = output.get("format", "unknown")
                desc = output.get("description", "")
                lines.append(f"### {str(output_type).title()} Output")
                lines.append(f"- **Format**: {format_spec}")

                if output.get("fields"):
                    lines.append(f"- **Fields**: {', '.join(map(str, output['fields']))}")
                
                if desc:
                    lines.append(f"- **Description**: {desc}")
                
                lines.append("")

        eval_criteria = idea_spec.get("evaluation_criteria", [])
        if eval_criteria:
            lines.append("## SUCCESS CRITERIA\n")
            lines.append("Your research will be evaluated on:\n")
            for criterion in eval_criteria:
                lines.append(f"- {criterion}")
            lines.append("")
        return "\n".join(lines)

    def generate_critic_prompt(self, critic_type: str,
                              idea: Dict[str, Any],
                              run_dir: Path) -> str:
        """
        Generate a critic/evaluation prompt.

        Args:
            critic_type: Type of critic (code_quality, scientific_rigor, reproducibility)
            idea: Original idea specification
            run_dir: Directory containing research outputs

        Returns:
            Complete critic prompt string
        """
        # Load critic template
        critic_template_path = f'evaluation/{critic_type}.txt'

        try:
            critic_template = self.load_template(critic_template_path)
        except FileNotFoundError:
            raise ValueError(f"Unknown critic type: {critic_type}")

        # Prepare variables
        idea_spec = idea.get('idea', {})
        variables = {
            'idea': idea_spec,
            'run_dir': str(run_dir),
            'notebooks_dir': str(run_dir / 'notebooks'),
            'results_dir': str(run_dir / 'results'),
            'logs_dir': str(run_dir / 'logs'),
        }

        # Compose prompt
        prompt = f"""
{'='*80}
EVALUATION TASK: {critic_type.upper().replace('_', ' ')}
{'='*80}

Research to Evaluate: {idea_spec.get('title', 'Untitled')}
Location: {run_dir}

{'='*80}

{critic_template}
"""

        # Render with variables
        rendered_prompt = self.render_template(prompt, variables)

        return rendered_prompt

    def generate_paper_writer_prompt(self, work_dir: Path, style: str = "neurips",
                                      style_config: Optional[Dict[str, Any]] = None,
                                      provider: str = "claude",
                                      domain: str = 'general') -> str:
        """
        Generate paper writer prompt from template.

        Args:
            work_dir: Workspace directory with experiment results
            style: Paper style (neurips, icml, acl, or any custom style)
            style_config: Style configuration dict with package_name, package_options, bib_style
            provider: AI provider (claude, codex, gemini) for skill path resolution
            domain: Research domain for template override lookup

        Returns:
            Complete prompt string for paper writing
        """
        # Load template (with domain override if available)
        template = self._load_template_with_domain_override('agents/paper_writer.txt', domain)

        # Load experiment results
        report_content = ""
        planning_content = ""
        lit_review_content = ""

        report_path = work_dir / "REPORT.md"
        planning_path = work_dir / "planning.md"
        lit_review_path = work_dir / "literature_review.md"

        report_content = self._read_text_or_default(report_path, "No REPORT.md found")
        planning_content = self._read_text_or_default(planning_path, "No planning.md found")
        lit_review_content = self._read_text_or_default(lit_review_path, "No literature_review.md found")

        # Determine author line from idea metadata
        author_line = "NeuriCo"
        idea_yaml_path = work_dir / ".neurico" / "idea.yaml"
        if idea_yaml_path.exists():
            try:
                idea_meta = yaml.safe_load(idea_yaml_path.read_text(encoding="utf-8"))
                submitter = idea_meta.get('idea', {}).get('metadata', {}).get('author')
                if submitter:
                    author_line = f"{submitter} and NeuriCo"
            except Exception:
                pass

        # Default style config if not provided
        if style_config is None:
            style_config = {
                'package_name': style,
                'package_options': '',
                'bib_style': 'plainnat'
            }

        # Build usepackage line based on config
        package_name = style_config.get('package_name', style)
        package_options = style_config.get('package_options', '')
        if package_options:
            usepackage_line = f"\\usepackage[{package_options}]{{{package_name}}}"
        else:
            usepackage_line = f"\\usepackage{{{package_name}}}"

        # Resolve provider-specific skill path
        skill_path = f".{provider}/skills/paper-writer/SKILL.md"

        # Prepare variables
        variables = {
            'style': style.upper(),
            'style_lower': style.lower(),
            'package_name': package_name,
            'package_options': package_options,
            'usepackage_line': usepackage_line,
            'bib_style': style_config.get('bib_style', 'plainnat'),
            'report_content': report_content,
            'planning_content': planning_content,
            'lit_review_content': lit_review_content,
            'author_line': author_line,
            'skill_path': skill_path,
        }

        return self.render_template(template, variables)

    def generate_session_instructions(self, prompt: str, work_dir: str,
                                       use_scribe: bool = False, domain: str = 'general',
                                       phase_summary: Optional[Dict[str, Any]] = None, state_snapshot: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate session instructions from template.

        Args:
            prompt: The research task prompt (from generate_research_prompt)
            work_dir: Working directory path for the research
            use_scribe: If True, include notebook instructions; if False, use Python scripts
            domain: Research domain for template override lookup
            phase_summary: Structured summary from the prior stage
            state_snapshot: Current StateManager snapshot as a dictionary.

        Returns:
            Complete session instructions string.

        Notes: 
            Support phase_summary and state_snapshot injection    
        """
        # Load template (with domain override if available)
        template = self._load_template_with_domain_override('agents/session_instructions.txt', domain)

        variables = {
            "prompt": prompt,
            "work_dir": work_dir,
            "use_scribe": use_scribe,
            "domain": domain,
            "phase_summary_section": self._format_phase_summary_section(phase_summary),
            "state_section": self._format_state_section(state_snapshot),
            "session_start": self._session_start_section(),
            "priority_section": self._priority_section(prompt),
            "code_workflow": self._code_workflow_section(use_scribe),
            "code_reminder": self._code_reminder_section(use_scribe),
        }
        return self.render_template(template, variables)

    def _format_phase_summary_section(self, phase_summary: Optional[Dict[str, Any]]) -> str:
        """
        Format prior phase summary for prompt injection.
        """
        if not phase_summary:
            return "No prior phase summary available."
        lines: List[str] = []

        stage = phase_summary.get("stage")
        if stage:
            lines.append(f"Stage: {stage}")

        summary_text = phase_summary.get("summary_text")
        if summary_text:
            lines.append(f"Summary: {summary_text}")
            lines.append("")
        
        self._append_list_section(lines, "Key Findings", phase_summary.get("key_findings", []))
        self._append_list_section(lines, "Decision Rationale", phase_summary.get("decision_rationale", []))
        self._append_list_section(lines, "Constraints and Failures", phase_summary.get("constraints_and_failures", []))

        top_k_candidates = phase_summary.get("top_k_candidates", [])
        if top_k_candidates:
            lines.append("Top-K Candidates:")
            for candidate in top_k_candidates:
                if isinstance(candidate, dict):
                    text = candidate.get("text", "")
                    candidate_type = candidate.get("type", "unknown")
                    score = candidate.get("score", 0.0)
                    lines.append(f"- [{candidate_type}, score={score}] {text}")
                else:
                    lines.append(f"- {candidate}")
            lines.append("")
        self._append_list_section(lines, "Recommended Next Steps", phase_summary.get("next_steps", []))
        return "\n".join(lines).strip() or "No prior phase summary available."

    def _format_state_section(self, state_snapshot: Optional[Dict[str, Any]]) -> str:
        """
        Format current runtime state for prompt injection
        """
        if not state_snapshot:
            return "No current execution state available."
        lines: List[str] = [
            f"Current Stage: {state_snapshot.get('current_stage', 'unknown')}",
            f"Current Phase: {state_snapshot.get('current_phase', 'unknown')}",
            f"Status: {state_snapshot.get('status', 'unknown')}",
        ]

        cwd = state_snapshot.get("cwd")
        if cwd:
            lines.append(f"Working Directory: {cwd}")

        last_updated = state_snapshot.get("last_updated")
        if last_updated:
            lines.append(f"Last Updated: {last_updated}")
        
        self._append_list_section(lines, "What Is Done", state_snapshot.get("what_is_done", []))
        self._append_list_section(lines, "Key Findings", state_snapshot.get("key_findings", []))
        self._append_list_section(lines, "Next Steps", state_snapshot.get("next_steps", []))

        notes = state_snapshot.get("notes")
        if notes:
            lines.append("Notes:")
            lines.append(str(notes))
            lines.append("")

        return "\n".join(lines).strip() or "No current execution state available."
    
    def _session_start_section(self) -> str:
        """
        Optional preamble for session templates.

        Kept as a helper so templates can use {{ session_start }} without requiring every caller to supply it.
        """
        return "" 
    
    def _priority_section(self, prompt: str) -> str:
        """
        Build a high-priority user-instruction section when present.

        User-provided instructions from the idea background should be surfaced near the top of the session prompt
        because they may contain constraints or preferences not captured elsewhere.
        """
        instructions = self._extract_user_instructions(prompt)
        if not instructions:
            return ""
        
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HIGH-PRIORITY USER INSTRUCTIONS
────────────────────────────────────────────────────────────────────────────────
{instructions}                        
═══════════════════════════════════════════════════════════════════════════════
"""
    def _code_workflow_section(self, use_scribe: bool) -> str:
        """
        Return implementation workflow text based on execution mode.
        """
        if use_scribe:
            return (
                "✓ Use notebooks for interactive implementation and analysis\n"
                "✓ Keep notebooks organized and executable from top to bottom\n"
                "✓ Save generated notebooks under notebooks\n"
                "✓ Export reusable code to src/ when appropriate"
            )
        return (
                "✓ Use Python scripts/modules for implementation\n"
                "✓ Put reusable code under src/ or scripts/\n"
                "✓ Keep experiments runnable from the command line\n"
                "✓ Save outputs under results and figures/"           
        )
    
    def _code_reminder_section(self, use_scribe: bool) -> str:
        """
        Return a short reminder matching the selected execution mode.
        """
        if use_scribe:
            return "Use notebooks for experiments, but keep outputs reproducible and documented."
        return "Use scripts/modules for experiments, and document how to rerun them."

    def generate_resource_finder_prompt(self, idea: Dict[str, Any]) -> str:
        """
        Generate resource finder prompt from template.

        Args:
            idea: Full idea specification (YAML dict)

        Returns:
            Complete prompt string for resource finder agent
        """
        idea_spec = idea.get('idea', {})
        domain = idea_spec.get('domain', 'general')

        # Load template (with domain override if available)
        template = self._load_template_with_domain_override('agents/resource_finder.txt', domain)

        # Extract key information
        title = idea_spec.get('title', 'Untitled Research')
        hypothesis = idea_spec.get('hypothesis', '')
        background = idea_spec.get('background', {})
        constraints = idea_spec.get('constraints', {})

        # Build research context section
        research_context = f"""
═══════════════════════════════════════════════════════════════════════════════
                         RESEARCH TOPIC SPECIFICATION
═══════════════════════════════════════════════════════════════════════════════

RESEARCH TITLE:
{title}

RESEARCH HYPOTHESIS:
{hypothesis}

RESEARCH DOMAIN:
{domain}
"""

        # Add background information if provided
        if background:
            research_context += "\nBACKGROUND INFORMATION:\n"

            if background.get("description"):
                research_context += f"\nDescription:\n{background['description']}\n"

            if background.get("papers"):
                research_context += "\nRelevant papers mentioned:\n"
                for paper in background['papers']:
                    if isinstance(paper, dict):
                        research_context += f"- {paper.get('title', paper.get('description', 'Unknown'))}"
                        if paper.get("url"):
                            research_context += f" ({paper['url']})"
                        if paper.get("path"):
                            research_context += f" ({paper['path']})"
                        research_context += "\n"
                    else:
                        research_context += f"- {paper}\n"

            if background.get('datasets'):
                research_context += "\nRelevant datasets mentioned:\n"
                for dataset in background['datasets']:
                    if isinstance(dataset, dict):
                        research_context += f"- {dataset.get('name', 'Unknown')}"
                        if dataset.get("source"):
                            research_context += f" (from: {dataset['source']})"
                        research_context += "\n"
                    else:
                        research_context += f"- {dataset}\n"

            if background.get('code_references'):
                research_context += "\n**CRITICAL - REPOSITORIES TO CLONE**:\n"
                research_context += ("The following repositories are EXPLICITLY SPECIFIED by the user and MUST be cloned:\n")
                for repo in background['code_references']:
                    if isinstance(repo, dict):
                        repo_url = repo.get('repo', repo.get('url', ''))
                        desc = repo.get('description', 'Code repository')
                        research_context += f"- {desc}\n"
                        research_context += f"  URL: {repo_url}\n"
                        research_context += f"  → You MUST clone this repository to code/ directory\n"
                    else:
                        research_context += f"- {repo}\n"
                research_context += "\nThese are NOT optional - they are specified by the research author.\n"

            if background.get('related_work'):
                research_context += f"\nRelated work:\n{background['related_work']}\n"

        # Add constraints if provided
        if constraints:
            research_context += "\nCONSTRAINTS AND REQUIREMENTS:\n"

            for key, value in constraints.items():
                research_context += f"- {key}: {value}\n"

        research_context += "\n" + "=" * 79 + "\n"

        return research_context + "\n" + template
    
    def generate_comment_prompt(self, idea: Dict[str, Any], work_dir: Path) -> str:
        """
        Generate comment handler prompt from template.

        This creates a lightweight prompt for making targeted improvements
        to existing workspaces based on user comments/feedback.

        Args:
            idea: Full idea specification (YAML dict) with 'comments' field
            work_dir: Working directory (existing workspace)

        Returns:
            Complete prompt string for comment handler agent
        """
        # Load template
        template = self.load_template('agents/comment_handler.txt')

        idea_spec = idea.get('idea', idea)

        # Extract key information
        title = idea_spec.get('title', 'Untitled Research')
        domain = idea_spec.get('domain', '')
        comments = idea_spec.get('comments', '')

        # Prepare variables for template
        variables = {
            'title': title,
            'domain': domain,
            'comments': comments,
            'work_dir': str(work_dir),
            'priority_section': "",
        }

        # Render template with variables
        return self.render_template(template, variables)

    def _extract_user_instructions(self, prompt: str) -> str:
        """
        Extract user-provided instructions from the prompt.
        Look for content in the "User-Provided Instructions and Context"
        section for content marked with >>> <<< delimiters.
        """
        import re
        pattern = r"###\s*User-Provided Instructions and Context:\s*\n>>>\s*(.*?)\s*<<<"
        match = re.search(pattern, prompt, re.DOTALL | re.IGNORECASE)
        if match:
            instructions = match.group(1).strip()
            if instructions and len(instructions) > 20:
                return instructions
            
        desc_pattern = r"description:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)"
        desc_match = re.search(desc_pattern, prompt, re.DOTALL | re.IGNORECASE)
        if desc_match:
            desc = desc_match.group(1).strip()
            action_words = [
                "run",
                "test",
                "implement",
                "use",
                "focus",
                "try",
                "ensure",
                "make sure",
                "should",
                "must",
            ]
            if any(word in desc.lower() for word in action_words) and len(desc) > 50:
                return desc
        return ""

    @staticmethod
    def _append_list_section(lines: List[str], title: str, items: Any) -> None:
        """
        Append a titled bullet list section if items are present.
        
        Args:
           lines: Output line buffer.
           title: Section title.
           items: List-like data or a single item.
        """
        if not items:
            return
    
        if isinstance(items, str):
            items = [items]
    
        lines.append(f"{title}:")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    @staticmethod
    def _read_text_or_default(path: Path, default: str) -> str:
        """Read text from path or return a default string if missing."""
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        return default

def main():
    """Test the prompt generator."""
    # Example usage
    generator = PromptGenerator()

    # Load an example idea
    example_idea = {
        'idea': {
            'title': 'Test Fine-tuning vs RAG',
            'domain': 'machine_learning',
            'hypothesis': 'Fine-tuning is more effective than RAG for specialized domains',
            'constraints': {
                'compute': 'gpu_required',
                'time_limit': 3600,
                'memory': '16GB'
            },
            'expected_outputs': [
                {
                    'type': 'metrics',
                    'format': 'json',
                    'fields': ['accuracy', 'f1_score']
                }
            ],
            'evaluation_criteria': [
                'Statistical significance (p < 0.05)',
                'Reproducible results'
            ]
        }
    }

    # Generate research prompt
    prompt = generator.generate_research_prompt(example_idea)
    print("Generated Prompt Length:", len(prompt))
    print("\nFirst 500 characters:")
    print(prompt[:500])


if __name__ == "__main__":
    main()
