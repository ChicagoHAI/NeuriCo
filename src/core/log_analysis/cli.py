import argparse
import json
from pathlib import Path

from core.log_analysis.run import find_run_repo
from core.log_analysis.ingest import load_prompt_texts, load_transcript_events
from core.log_analysis.parser.prompt_parser import parse_task_spec
from core.log_analysis.trajectory.trajectory_builder import build_trajectory
from core.log_analysis.datastore.event_store_writer import EventStoreWriter

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--parsed-root", required=True)
    args = parser.parse_args()
    raw_root = Path(args.raw_root)
    parsed_root = Path(args.parsed_root)
    parsed_root.mkdir(parents=True, exist_ok=True)

    repos = find_run_repo(raw_root)

    for repo in repos:
        prompt_texts = load_prompt_texts(repo)
        raw_events = load_transcript_events(repo)
        task = parse_task_spec(repo.run_id, prompt_texts)
        trajectory = build_trajectory(repo, task, raw_events)
        out_dir = parsed_root / repo.title_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        trajectory_json_path = out_dir / "trajectory.json"
        trajectory_events_path = out_dir / "trajectory_events.jsonl"
        trajectory_json_path.write_text(
            trajectory.model_dump_json(indent=2),
            encoding="utf-8",
        )
        with open(trajectory_events_path, "w", encoding="utf-8") as f:
            for step in trajectory.steps:
                f.write(json.dumps(step.model_dump(mode="json"), ensure_ascii=False) + "\n")
        writer = EventStoreWriter(db_work_dir=out_dir)
        writer.write(trajectory)
        print(
            f"Parsed {repo.run_id}: "
            f"{len(trajectory.steps)} steps, "
            f"{len(trajectory.artifacts)} artifacts, "
            f"{len(trajectory.failures)} failures"
        )
if __name__ == "__main__":
    main()