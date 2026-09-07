"""Agents the HITL manager may schedule between iterations."""

MANAGER_CALLABLE_AGENTS = frozenset({"resource_finder"})


def manager_callable_agent(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized in MANAGER_CALLABLE_AGENTS:
        return normalized
    allowed = ", ".join(sorted(MANAGER_CALLABLE_AGENTS))
    raise ValueError(f"Agent {normalized!r} is not manager-callable. Choose from: {allowed}.")
