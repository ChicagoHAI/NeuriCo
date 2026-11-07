"""stdio entrypoint for the NeuriCo Harbor ACP agent."""

from __future__ import annotations

import asyncio

from acp import run_agent

from .codex_bootstrap import _ensure_git_available


async def _run() -> None:
    # Import NeuriCo only after Git exists. GitPython resolves the executable
    # during import and otherwise remains unavailable for AutoResearch's local
    # checkpoint manager even if Git is installed later.
    from .agent import NeuricoHarborAgent

    await run_agent(NeuricoHarborAgent())


def main() -> None:
    _ensure_git_available()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
