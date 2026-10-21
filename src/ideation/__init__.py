"""Ideation: problem -> ideation -> idea_judge, ported from sai-review's safety digest.

See ``src/ideation/NOTICE.md`` for the origin and ``docs/IDEATION_INTEGRATION.md`` for the
design. ``runtime.IdeationRun`` drives the stages through ``core.agent_factory``; ``to_job``
projects the ranked ideas onto NeuriCo job specs, which ``safety.planner.validate_proposals``
gates into the queue as for every other planner round.
"""
