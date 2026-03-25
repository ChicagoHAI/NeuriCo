# Templates

This directory contains all prompt templates that guide NeuriCo's research agents.

## Directory Structure

```
templates/
├── base/                     # Universal research methodology (loaded for ALL domains)
│   └── researcher.txt        # Core research workflow and standards
│
├── agents/                   # Default agent templates (shared across domains)
│   ├── session_instructions.txt   # Main research execution workflow
│   ├── paper_writer.txt           # Paper writing instructions
│   ├── resource_finder.txt        # Literature & resource gathering
│   └── comment_handler.txt        # Feedback handling
│
├── domains/                  # Domain-specific guidance and overrides
│   ├── <domain_name>/
│   │   ├── core.txt               # Domain methodology (REQUIRED for has_template: true)
│   │   ├── session_instructions.txt   # Override for agents/session_instructions.txt (optional)
│   │   ├── paper_writer.txt           # Override for agents/paper_writer.txt (optional)
│   │   └── resource_finder.txt        # Override for agents/resource_finder.txt (optional)
│   └── ...
│
├── paper_styles/             # LaTeX paper format templates
│   ├── neurips/
│   ├── icml/
│   └── ams/
│
├── paper_writing/            # Paper writing guides and LaTeX commands
├── evaluation/               # Research evaluation criteria
└── skills/                   # Claude Code skills
```

## How Templates Are Composed

When a research idea specifies `domain: X`, the system loads templates in this order:

1. `base/researcher.txt` — universal methodology (always loaded)
2. `domains/X/core.txt` — domain-specific guidance (if exists, else falls back to default domain)
3. For each agent (session, paper writer, resource finder):
   - Check `domains/X/{agent_template}.txt` — domain-specific override
   - Fall back to `agents/{agent_template}.txt` — universal default

## Adding a New Domain

1. Create `templates/domains/<domain_name>/core.txt` with domain-specific methodology
2. Register the domain in `config/domains.yaml` with `has_template: true`
3. Add domain keywords to `src/cli/fetch_from_ideahub.py` (`_DOMAIN_KEYWORDS` dict)
4. (Optional) Add agent override files in the same directory if the domain needs significantly different agent behavior (e.g., mathematics overrides the paper writer for AMS LaTeX format)

See `domains/mathematics/` for an example with agent overrides, or `domains/battery/` for a simpler domain with only `core.txt`.
