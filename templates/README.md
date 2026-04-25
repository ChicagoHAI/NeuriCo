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

`config/domains.yaml` is the single source of truth — adding a new domain
is a config edit, not a code change.

1. Add an entry to `config/domains.yaml`:
   ```yaml
   my_domain:
     name: "My Domain"
     description: "Short description of what this domain covers"
     has_template: true        # set to false to use the default template
     paper_style: my_style     # optional; falls back to default_paper_style
     keywords:                  # optional; used by IdeaHub auto-classification
       - keyword1
       - keyword2
   ```

2. (Optional) Create `templates/domains/<my_domain>/core.txt` with
   domain-specific methodology. Required if `has_template: true`.

3. (Optional) Add agent override files in the same directory if the domain
   needs significantly different agent behavior. Available overrides:
   - `templates/domains/<my_domain>/paper_writer.txt`
   - `templates/domains/<my_domain>/resource_finder.txt`
   - `templates/domains/<my_domain>/session_instructions.txt`

   Each falls back to the universal version in `templates/agents/` if the
   override file is absent.

4. (Optional) If you specified a custom `paper_style`, create
   `templates/paper_styles/<my_style>/` with `style_config.yaml` and an
   `example_paper.tex`.

No source code changes are needed. The runner, prompt generator, and IdeaHub
fetcher all read from `config/domains.yaml` at runtime.

See `domains/mathematics/` for an example with full agent overrides, or
`domains/battery/` for a simpler domain with only `core.txt`.
