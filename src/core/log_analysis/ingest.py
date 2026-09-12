import json
from pathlib import Path
from .models import RawTranscriptEvent, RunRepo

def read_text_file(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")

def load_prompt_texts(repo: RunRepo) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in repo.prompt_files:
        result[str(path)] = read_text_file(path)
    return result

def load_transcript_events(repo: RunRepo) -> list[RawTranscriptEvent]:
    events: list[RawTranscriptEvent] = []
    for path in repo.transcript_files:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    raw = {
                        "type": "json_parse_error",
                        "message": line,
                    }
                events.append(
                    RawTranscriptEvent(
                        run_id=repo.run_id,
                        source_file=str(path),
                        line_no=line_no,
                        raw_event_type=raw.get("type"),
                        timestamp=raw.get("timestamp"),
                        raw=raw,
                    )                       
                )
    return events
