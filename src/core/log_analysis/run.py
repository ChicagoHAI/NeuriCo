from pathlib import Path
from .models import RunRepo

PROMPT_PATTERNS = [
    "*prompt*.txt",
    "*instructions*.txt",
]

TRANSCRIPT_PATTERNS = [
    "*transctipt*.jsonl",
    "*.jsonl",
]

def find_run_repo(raw_root: Path) -> list[RunRepo]:
    raw_root = Path(raw_root)
    repos: list[RunRepo] = []
    for task_dir in sorted(raw_root.iterdir()):
        if not task_dir.is_dir():
            continue
        prompt_files : list[Path] = []
        for pattern in PROMPT_PATTERNS:
            prompt_files.extend(task_dir.glob(pattern))
        transcript_files: list[Path] = []
        for pattern in TRANSCRIPT_PATTERNS:
            transcript_files.extend(task_dir.glob(pattern))
        prompt_files = sorted(set(prompt_files))
        transcript_files = sorted(set(transcript_files))

        if not prompt_files and not transcript_files:
            continue

        artifact_files = [
            path for path in task_dir.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.name != ".DS_Store"
        ]

        repos.append(
            RunRepo(
                run_id=task_dir.name,
                title_slug=task_dir.name,
                root_dir=task_dir,
                prompt_files=prompt_files,
                transcript_files=transcript_files,
                artifact_files=artifact_files,
            )
        )
    return repos
