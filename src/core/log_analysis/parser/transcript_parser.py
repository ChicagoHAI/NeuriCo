from core.log_analysis.models import RawTranscriptEvent
def parse_codex_events(
    raw_events: list[RawTranscriptEvent],
) -> list[RawTranscriptEvent]:
    return raw_events