"""Fixture-only entrypoint; never selected by the production source manifest."""

import os

from neurico_harbor_agent import __main__, agent

if os.environ.get("NEURICO_FIXTURE_PUBLIC_FAILURE") == "1":

    def fail(*args, **kwargs):
        raise OSError("fixture public export failure")

    agent.export_harbor_research_artifacts = fail

__main__.main()
