"""Validation for agents exposed at manager-controlled insertion boundaries."""

MANAGER_CALLABLE_AGENTS = frozenset({"resource_finder"})


def manager_callable_agent(name: str) -> str:
    agent = str(name).strip().lower().replace("-", "_")
    if agent not in MANAGER_CALLABLE_AGENTS:
        available = ", ".join(sorted(MANAGER_CALLABLE_AGENTS))
        raise ValueError(f"Unsupported manager-callable agent '{name}'. Available: {available}")
    return agent
