import importlib.util
import re
import sys
from pathlib import Path

import pytest
from git import Repo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from baseline import zero_shot  # noqa: E402
from core.agent_cli import MODEL_ENV_VAR, build_agent_command, model_slug  # noqa: E402
from core.github_manager import GitHubManager  # noqa: E402
from core.security import (  # noqa: E402
    MAX_SCAN_BYTES, binary_files_with_secrets, find_secrets, sanitize_files, sanitize_logs_directory,
    sanitize_text,
)


def _load_run_methods():
    spec = importlib.util.spec_from_file_location(
        "run_methods", PROJECT_ROOT / "scripts" / "run_methods.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_methods"] = module
    spec.loader.exec_module(module)
    return module


IDEA = {
    "idea": {
        "title": "Do LLMs keep obvious secrets?",
        "domain": "artificial_intelligence",
        "hypothesis": "Models leak a secret word into stories even when told not to.",
        "metadata": {"github_repo_name": "should-not-reach-the-prompt"},
    }
}


# -- model selection -----------------------------------------------------------

def test_agent_command_includes_explicit_model(monkeypatch):
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    claude = build_agent_command("claude", full_permissions=True, model="claude-opus-5-5")
    codex = build_agent_command("codex", full_permissions=True, model="gpt-5.6-sol")
    assert claude == (
        "claude -p --dangerously-skip-permissions --model claude-opus-5-5 "
        "--verbose --output-format stream-json"
    )
    assert codex == "codex exec --yolo --model gpt-5.6-sol --json"


def test_agent_command_uses_run_wide_model_override(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR, "gpt-6-astra")
    assert "--model gpt-6-astra" in build_agent_command("codex", full_permissions=True)


def test_agent_command_without_model_keeps_cli_default(monkeypatch):
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    assert "--model" not in build_agent_command("claude", full_permissions=True)


def test_model_slug_drops_repeated_provider_prefix():
    assert model_slug("claude", "claude-opus-5-5") == "opus-5-5"
    assert model_slug("codex", "gpt-5.6-sol") == "gpt-5-6-sol"


# -- workspace naming ----------------------------------------------------------

def _neurico_name(provider, model):
    namer = GitHubManager.__new__(GitHubManager)
    return namer._generate_repo_name(
        IDEA["idea"]["title"], "artificial_intelligence", "fallback", provider=provider, model=model
    )


def test_neurico_workspace_names_carry_the_model():
    assert re.fullmatch(
        r"do-llms-keep-obvious-secrets-[0-9a-f]{4}-claude-opus-5-5",
        _neurico_name("claude", "claude-opus-5-5"),
    )
    assert re.fullmatch(
        r"do-llms-keep-obvious-secrets-[0-9a-f]{4}-codex-gpt-5-6-sol",
        _neurico_name("codex", "gpt-5.6-sol"),
    )


def test_neurico_workspace_name_without_model_is_unchanged():
    assert re.fullmatch(
        r"do-llms-keep-obvious-secrets-[0-9a-f]{4}-claude", _neurico_name("claude", None)
    )


@pytest.mark.parametrize(
    "provider,model,suffix",
    [
        ("claude", "claude-opus-5-5", "zeroshot-claude-opus-5-5"),
        ("claude", "claude-fable-5-1", "zeroshot-claude-fable-5-1"),
        ("codex", "gpt-5.6-sol", "zeroshot-codex-gpt-5-6-sol"),
        ("codex", "gpt-6-astra", "zeroshot-codex-gpt-6-astra"),
    ],
)
def test_baseline_workspace_names_are_distinct_from_neurico(provider, model, suffix):
    name = zero_shot.generate_workspace_name(IDEA, provider, model)
    assert re.fullmatch(rf"do-llms-keep-obvious-secrets-[0-9a-f]{{4}}-{suffix}", name)
    # Valid GitHub repository name, and never a NeuriCo name for the same model.
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name)
    assert not re.fullmatch(r".*-[0-9a-f]{4}-(claude|codex)-.*", name)


def test_prepare_local_workspace_uses_configured_parent(tmp_path):
    workspace = zero_shot.prepare_workspace(
        IDEA, "codex", "gpt-6-astra", github_manager=None, workspace_parent=tmp_path
    )
    assert workspace["work_dir"].parent == tmp_path
    assert workspace["work_dir"].is_dir()
    assert workspace["repo_name"].endswith("-zeroshot-codex-gpt-6-astra")
    assert workspace["github_url"] is None


# -- prompt --------------------------------------------------------------------

def test_prompt_contains_idea_and_names_but_never_values_of_keys():
    env = {"OPENROUTER_KEY": "sk-or-v1-" + "a" * 40, "OPENAI_API_KEY": "sk-proj-" + "b" * 40}
    prompt = zero_shot.build_prompt(IDEA, 5 * 3600, environment=env)
    assert "Do LLMs keep obvious secrets?" in prompt
    assert "Models leak a secret word" in prompt
    assert "about 5 hours;" in prompt
    assert "`OPENROUTER_KEY`" in prompt and "`OPENAI_API_KEY`" in prompt
    assert env["OPENROUTER_KEY"] not in prompt and env["OPENAI_API_KEY"] not in prompt
    assert "should-not-reach-the-prompt" not in prompt  # runtime metadata is dropped
    assert "paper_draft/main.pdf" in prompt
    assert not re.search(r"\{(time_budget|api_keys|idea_yaml)\}", prompt)


def test_prompt_keeps_multiline_idea_text_readable():
    idea = {"idea": {"title": "T", "hypothesis": "First line.  \nSecond line: with colon.\n"}}
    prompt = zero_shot.build_prompt(idea, 3600, environment={})
    assert "  hypothesis: |-\n    First line.\n    Second line: with colon." in prompt
    assert "about 1 hour;" in prompt


def test_prompt_without_api_keys_says_so():
    assert "No LLM API keys are configured" in zero_shot.build_prompt(IDEA, 600, environment={})


def test_load_idea_rejects_missing_hypothesis(tmp_path):
    path = tmp_path / "idea.yaml"
    path.write_text("idea:\n  title: Something\n")
    with pytest.raises(ValueError):
        zero_shot.load_idea(path)


# -- API key leak protection ---------------------------------------------------

def test_sanitize_redacts_exact_values_of_credential_env_vars(monkeypatch):
    # No recognizable prefix, so only the value match can catch these.
    monkeypatch.setenv("S2_API_KEY", "Zq8mN3xT7vB2kLp9WcR4")
    monkeypatch.setenv("COHERE_API_KEY", "h7Jk2LmN9pQrStUv3WxY")
    text = "curl -H 'x-api-key: Zq8mN3xT7vB2kLp9WcR4' ... co=h7Jk2LmN9pQrStUv3WxY"
    cleaned = sanitize_text(text)
    assert "Zq8mN3xT7vB2kLp9WcR4" not in cleaned and "h7Jk2LmN9pQrStUv3WxY" not in cleaned
    assert "[REDACTED_S2_API_KEY]" in cleaned
    assert sorted(find_secrets(text)) == ["COHERE_API_KEY", "S2_API_KEY"]


def test_sanitize_ignores_short_or_non_credential_env_values(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "short")
    monkeypatch.setenv("WORKSPACE_NAME", "a-perfectly-ordinary-value")
    text = "short a-perfectly-ordinary-value"
    assert sanitize_text(text) == text


def test_sanitize_logs_directory_reaches_nested_logs(tmp_path):
    nested = tmp_path / "logs" / "attempt_1"
    nested.mkdir(parents=True)
    key = "sk-ant-" + "c" * 30
    (nested / "agent_transcript.jsonl").write_text(f'{{"text": "{key}"}}\n')
    assert sanitize_logs_directory(tmp_path / "logs") == 1
    assert key not in (nested / "agent_transcript.jsonl").read_text()


def test_redact_workspace_secrets_covers_files_outside_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-v1-" + "d" * 40)
    key = "sk-or-v1-" + "d" * 40
    repo = Repo.init(tmp_path)
    (tmp_path / ".gitignore").write_text("data/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "run.py").write_text(f'API_KEY = "{key}"\n')
    (tmp_path / "README.md").write_text("clean file\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ignored.txt").write_text(key)  # ignored, never published
    (tmp_path / "weights.bin").write_bytes(b"\xff\xfe\x00binary")

    assert zero_shot.redact_workspace_secrets(tmp_path) == ["src/run.py"]
    assert key not in (tmp_path / "src" / "run.py").read_text()
    assert (tmp_path / "README.md").read_text() == "clean file\n"
    repo.close()


def test_hugging_face_tokens_are_redacted_by_pattern(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    token = "hf_" + "aB3" * 12
    assert sanitize_text(f"login(token='{token}')") == "login(token='[REDACTED_HF_TOKEN]')"
    assert find_secrets(f"x {token}") == ["[REDACTED_HF_TOKEN]"]
    assert sanitize_text("hf_hub_download and hf_short") == "hf_hub_download and hf_short"


def test_echoed_env_assignments_are_redacted_in_logs_only():
    line = "HF_TOKEN=abcdefghijkl S2_API_KEY=zzzzzzzzzzzz OTHER=keep"
    assert sanitize_text(line) == "HF_TOKEN=[REDACTED] S2_API_KEY=[REDACTED] OTHER=keep"
    # Source files keep harmless assignments; only real key values change there.
    assert sanitize_text("docker run -e HF_TOKEN=$HF_TOKEN", assignments=False) == (
        "docker run -e HF_TOKEN=$HF_TOKEN")


def test_commit_and_push_redacts_keys_in_staged_files_outside_logs(tmp_path, monkeypatch):
    token = "hf_" + "Zx9" * 12
    monkeypatch.setenv("HF_TOKEN", token)
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True)
    work = tmp_path / "work"
    repo = Repo.init(work)
    repo.create_remote("origin", str(remote))
    (work / "src").mkdir()
    (work / "src" / "load.py").write_text(f'TOKEN = "{token}"\n')
    (work / "notes.md").write_text("no secrets here\n")
    (work / "blob.bin").write_bytes(b"\xff\xfe\x00")

    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "unused"
    assert manager.commit_and_push(work, "test commit") is True

    pushed = Repo(remote)
    content = pushed.git.show("main:src/load.py")
    assert token not in content and "[REDACTED_HF_TOKEN]" in content
    assert pushed.git.show("main:notes.md") == "no secrets here"
    assert token not in pushed.git.log("-p", "--all")
    repo.close()


def test_mapbox_tokens_are_redacted():
    for prefix in ("sk", "pk"):
        token = f"{prefix}.eyJ" + "a" * 40 + "." + "b" * 20
        assert sanitize_text(f"url?access_token={token}") == "url?access_token=[REDACTED_MAPBOX_TOKEN]"


def test_commit_and_push_excludes_core_dumps_and_binaries_with_keys(tmp_path, monkeypatch):
    token = "hf_" + "Qw7" * 12
    monkeypatch.setenv("HF_TOKEN", token)
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True)
    work = tmp_path / "work"
    repo = Repo.init(work)
    repo.create_remote("origin", str(remote))
    (work / "core.1234").write_bytes(b"\x7fELF" + b"\x00" * 64 + token.encode() + b"\x00" * 8)
    (work / "state.pkl").write_bytes(b"\x80\x04" + token.encode() + b"\xff\xfe")
    (work / "data.bin").write_bytes(b"\x00\x01\x02 clean binary \xff")
    (work / "README.md").write_text("clean text\n")
    assert sorted(binary_files_with_secrets(work, ["core.1234", "state.pkl", "data.bin", "README.md"])) == [
        "core.1234", "state.pkl"]

    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "unused"
    assert manager.commit_and_push(work, "test commit") is True
    pushed = sorted(Repo(remote).git.ls_tree("-r", "--name-only", "main").splitlines())
    assert pushed == ["README.md", "data.bin"]
    assert token.encode() not in Repo(remote).git.log("-p", "--all").encode()
    repo.close()


# -- batch script --------------------------------------------------------------

def test_each_slot_has_its_own_queue_across_ideas():
    run_methods = _load_run_methods()
    methods = [run_methods.Method(*row) for row in run_methods.METHODS]
    ideas = [Path("a.yaml"), Path("b.yaml")]
    slots = {
        slot: [(idea.stem, method.label) for idea, method in queue]
        for slot, queue in run_methods.plan_slots(ideas, methods).items()
    }
    assert slots == {
        "neurico": [
            ("a", "neurico-claude-claude-opus-5-5"), ("a", "neurico-codex-gpt-5-6-sol"),
            ("a", "neurico-claude-claude-fable-5-1"), ("a", "neurico-codex-gpt-6-astra"),
            ("b", "neurico-claude-claude-opus-5-5"), ("b", "neurico-codex-gpt-5-6-sol"),
            ("b", "neurico-claude-claude-fable-5-1"), ("b", "neurico-codex-gpt-6-astra"),
        ],
        "zero-shot-claude": [
            ("a", "zero-shot-claude-claude-opus-5-5"), ("a", "zero-shot-claude-claude-fable-5-1"),
            ("b", "zero-shot-claude-claude-opus-5-5"), ("b", "zero-shot-claude-claude-fable-5-1"),
        ],
        "zero-shot-codex": [
            ("a", "zero-shot-codex-gpt-5-6-sol"), ("a", "zero-shot-codex-gpt-6-astra"),
            ("b", "zero-shot-codex-gpt-5-6-sol"), ("b", "zero-shot-codex-gpt-6-astra"),
        ],
    }


def test_resume_spec_is_read_from_the_workspace_name():
    run_methods = _load_run_methods()
    assert run_methods.parse_resume("my-idea-9797-zeroshot-claude-opus-5-5") == (
        "my-idea-9797-zeroshot-claude-opus-5-5", "claude", "opus-5-5")
    with pytest.raises(SystemExit):
        run_methods.parse_resume("my-idea-6bce-claude-opus-5-5")


def test_neurico_resume_must_name_one_method():
    run_methods = _load_run_methods()
    methods = [run_methods.Method(*row) for row in run_methods.METHODS]
    neurico = [m for m in methods if m.method == "neurico"]
    assert len(neurico) > 1
    # bare form with several NeuriCo methods selected: refused
    with pytest.raises(SystemExit):
        run_methods.parse_neurico_resumes(["my_idea=idea_123"], methods)
    # explicit method label: applies to that method only
    label = neurico[1].label
    assert run_methods.parse_neurico_resumes([f"my_idea/{label}=idea_123"], methods) == {
        ("my_idea", label): "idea_123"}
    # bare form with exactly one NeuriCo method selected: fine
    one = [neurico[0]] + [m for m in methods if m.method != "neurico"]
    assert run_methods.parse_neurico_resumes(["my_idea=idea_123"], one) == {
        ("my_idea", neurico[0].label): "idea_123"}
    with pytest.raises(SystemExit):
        run_methods.parse_neurico_resumes(["my_idea/not-a-method=idea_123"], methods)


def test_every_publishable_file_is_scanned():
    from core.github_manager import MAX_FILE_SIZE

    # One boundary for both: files up to 50 MiB are scanned and may be pushed,
    # anything larger is neither scanned nor published.
    assert MAX_SCAN_BYTES == MAX_FILE_SIZE == 50 * 1024 * 1024


def test_large_files_are_skipped_not_scanned(tmp_path):
    big = tmp_path / "big.bin"
    with big.open("wb") as fh:
        fh.seek(MAX_SCAN_BYTES)
        fh.write(b"sk-" + b"A" * 60)  # secret placed past the boundary
    small = tmp_path / "small.txt"
    small.write_text("key sk-" + "A" * 60)
    assert binary_files_with_secrets(tmp_path, ["big.bin", "small.txt"]) == []  # big skipped, small is text
    sanitize_files(tmp_path, ["big.bin", "small.txt"])
    assert "sk-" + "A" * 60 not in small.read_text()
    assert big.stat().st_size > MAX_SCAN_BYTES  # untouched


def test_resume_modes_give_distinct_instructions():
    assert "Do not run new experiments" in zero_shot.RESUME_NOTES["writeup"]
    assert "Do not start over" in zero_shot.RESUME_NOTES["continue"]
    assert "Do not run new experiments" not in zero_shot.RESUME_NOTES["continue"]


def test_resume_reuses_the_workspace_and_keeps_earlier_logs(tmp_path, monkeypatch):
    workspace = zero_shot.prepare_workspace(
        IDEA, "claude", "claude-opus-5-5", github_manager=None, workspace_parent=tmp_path
    )
    zero_shot.write_metadata(workspace["work_dir"], IDEA, {"github_url": None, "status": "completed"})
    reopened = zero_shot.open_existing_workspace(workspace["repo_name"], workspace_parent=tmp_path)
    assert reopened["work_dir"] == workspace["work_dir"]
    assert reopened["run_info"]["status"] == "completed"
    with pytest.raises(ValueError):
        zero_shot.open_existing_workspace("not-a-workspace", workspace_parent=tmp_path)
    assert set(zero_shot.RESUME_NOTES) == {"writeup", "continue"}


def test_no_run_is_cut_off_by_default():
    run_methods = _load_run_methods()
    assert run_methods.RESOURCE_FINDER_TIMEOUT == 0
    assert run_methods.EXPERIMENT_TIMEOUT == 0
    assert run_methods.PAPER_TIMEOUT == 0
    assert run_methods.ZERO_SHOT_TIMEOUT == 0


def test_prompt_without_timeout_sets_no_time_budget():
    prompt = zero_shot.build_prompt(IDEA, None, environment={})
    assert "There is no time limit" in prompt
    assert "time budget" not in prompt
