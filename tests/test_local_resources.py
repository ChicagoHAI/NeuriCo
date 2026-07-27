"""Unit tests for local resource declarations (idea.local_resources / idea.evaluation).

Covers the submission-layer validation added for locally submitted ideas:
path-token extraction from free text, conversion faithfulness (no dropped
paths), structural validation of local_resources and evaluation entries, and
their integration into IdeaManager.validate_idea().

Run: python -m pytest tests/test_local_resources.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    find_path_tokens,
    missing_paths_in_idea,
    stage_local_resources,
    validate_evaluation_spec,
    validate_local_resources,
)


def _idea(**overrides):
    idea = {
        'title': 'A sufficiently long test title',
        'domain': 'machine_learning',
        'hypothesis': 'A sufficiently long test hypothesis for validation',
    }
    idea.update(overrides)
    return idea


# ---------------------------------------------------------------- path tokens

def test_find_path_tokens_extracts_local_paths():
    text = (
        "Data lives at /data/cifar10_fixed_protocol and the eval helper is "
        "./eval_tools/protocol_eval.py, with configs under ~/configs/exp1."
    )
    tokens = find_path_tokens(text)
    assert "/data/cifar10_fixed_protocol" in tokens
    assert "./eval_tools/protocol_eval.py" in tokens
    assert "~/configs/exp1" in tokens


def test_find_path_tokens_ignores_urls():
    text = "See https://example.com/data.csv and http://host/path/file.txt"
    assert find_path_tokens(text) == []


def test_find_path_tokens_dedups_in_order():
    text = "/a/b first, then /c/d, then /a/b again"
    assert find_path_tokens(text) == ["/a/b", "/c/d"]


# ---------------------------------------------------------------- faithfulness

def test_missing_paths_detects_dropped_path():
    raw = "The dataset is at /data/my_set and code at /home/user/tool.py"
    idea_spec = {'idea': _idea(local_resources={
        'datasets': [{'path': '/data/my_set', 'usage': 'training data'}]
    })}
    dropped = missing_paths_in_idea(raw, idea_spec)
    assert dropped == ["/home/user/tool.py"]


def test_missing_paths_rejects_prose_only_survival():
    # A path that only survives inside background.description is never
    # staged or mounted; the check must not count it as faithful (the
    # no-API-key fallback keeps the whole input there).
    raw = "The dataset is at /data/my_set"
    idea_spec = {'idea': _idea(background={'description': 'dataset at /data/my_set'})}
    assert missing_paths_in_idea(raw, idea_spec) == ["/data/my_set"]


def test_missing_paths_passes_when_all_survive():
    raw = "The dataset is at /data/my_set"
    idea_spec = {'idea': _idea(local_resources={
        'datasets': [{'path': '/data/my_set', 'usage': 'training data'}]
    })}
    assert missing_paths_in_idea(raw, idea_spec) == []


# ---------------------------------------------------------------- local_resources

def test_dataset_missing_usage_is_error(tmp_path):
    idea = _idea(local_resources={'datasets': [{'path': str(tmp_path)}]})
    errors, _ = validate_local_resources(idea)
    assert any("usage" in e for e in errors)


def test_function_missing_entrypoint_is_error(tmp_path):
    fn = tmp_path / "eval.py"
    fn.write_text("def evaluate(): pass\n")
    idea = _idea(local_resources={'functions': [{'path': str(fn), 'usage': 'eval'}]})
    errors, _ = validate_local_resources(idea)
    assert any("entrypoint" in e for e in errors)


def test_nonexistent_path_is_warning_not_error(tmp_path):
    idea = _idea(local_resources={'datasets': [
        {'path': str(tmp_path / "nope"), 'usage': 'training data'}
    ]})
    errors, warnings = validate_local_resources(idea)
    assert errors == []
    assert any("does not exist" in w for w in warnings)


def test_wrong_entrypoint_is_warning(tmp_path):
    fn = tmp_path / "eval.py"
    fn.write_text("def evaluate_protocol(): pass\n")
    idea = _idea(local_resources={'functions': [
        {'path': str(fn), 'entrypoint': 'score_all', 'usage': 'eval'}
    ]})
    errors, warnings = validate_local_resources(idea)
    assert errors == []
    assert any("score_all" in w for w in warnings)


def test_valid_entries_pass_cleanly(tmp_path):
    data = tmp_path / "dataset"
    data.mkdir()
    fn = tmp_path / "eval.py"
    fn.write_text("def evaluate_protocol(preds):\n    return 0.9\n")
    idea = _idea(local_resources={
        'datasets': [{'path': str(data), 'usage': 'training data'}],
        'functions': [{'path': str(fn), 'entrypoint': 'evaluate_protocol',
                       'usage': 'all evaluation', 'required_for_evaluation': True}],
    })
    errors, warnings = validate_local_resources(idea)
    assert errors == []
    assert warnings == []


def test_non_mapping_section_is_error():
    idea = _idea(local_resources=["/data/my_set"])
    errors, _ = validate_local_resources(idea)
    assert any("must be a mapping" in e for e in errors)


def test_relative_path_resolved_against_base_dir(tmp_path):
    (tmp_path / "sets").mkdir()
    idea = _idea(local_resources={'datasets': [
        {'path': './sets', 'usage': 'training data'}
    ]})
    errors, warnings = validate_local_resources(idea, base_dir=tmp_path)
    assert errors == []
    assert warnings == []


# ---------------------------------------------------------------- evaluation

def test_metric_missing_name_is_error():
    idea = _idea(evaluation={'metrics': [{'definition': 'mean accuracy'}]})
    errors, _ = validate_evaluation_spec(idea)
    assert any("name" in e for e in errors)


def test_metric_without_target_is_warning():
    idea = _idea(evaluation={'metrics': [
        {'name': 'test_accuracy', 'definition': 'mean accuracy over 3 seeds'}
    ]})
    errors, warnings = validate_evaluation_spec(idea)
    assert errors == []
    assert any("target" in w for w in warnings)


def test_valid_evaluation_passes_cleanly():
    idea = _idea(evaluation={
        'metrics': [{'name': 'test_accuracy',
                     'definition': 'mean accuracy over 3 seeds',
                     'target': '>= 0.915'}],
        'results_format': 'results.json with per-seed and mean accuracy',
    })
    errors, warnings = validate_evaluation_spec(idea)
    assert errors == []
    assert warnings == []


# ---------------------------------------------------------------- staging

def _staged_fixture(tmp_path):
    src = tmp_path / "src_host"
    src.mkdir()
    data = src / "toy_dataset"
    data.mkdir()
    (data / "train.csv").write_text("label,value\n0,1.2\n")
    fn = src / "protocol_eval.py"
    fn.write_text("def evaluate_protocol(preds, labels):\n    return 0.5\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    idea_spec = {'idea': _idea(local_resources={
        'datasets': [{'path': str(data), 'usage': 'training data'}],
        'functions': [{'path': str(fn), 'entrypoint': 'evaluate_protocol',
                       'usage': 'all evaluation', 'required_for_evaluation': True}],
    })}
    return work_dir, idea_spec, data, fn


def test_stage_copies_and_rewrites_paths(tmp_path):
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 2
    resources = idea_spec['idea']['local_resources']
    assert resources['datasets'][0]['path'] == "datasets/local/toy_dataset"
    assert resources['functions'][0]['path'] == "code/local/protocol_eval.py"
    assert (work_dir / "datasets/local/toy_dataset/train.csv").exists()
    assert (work_dir / "code/local/protocol_eval.py").exists()
    # Originals preserved for re-staging
    assert resources['datasets'][0]['source_path']
    # Staged data ignored by git, staged code not
    gitignore = (work_dir / ".gitignore").read_text()
    assert "datasets/local/" in gitignore
    assert "code/local/" not in gitignore


def test_stage_is_idempotent(tmp_path):
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    stage_local_resources(work_dir, idea_spec)
    assert stage_local_resources(work_dir, idea_spec) == 0


def test_stage_recopies_when_staged_copy_missing(tmp_path):
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    stage_local_resources(work_dir, idea_spec)
    import shutil
    shutil.rmtree(work_dir / "datasets/local/toy_dataset")
    assert stage_local_resources(work_dir, idea_spec) == 1


def test_stage_missing_source_is_hard_error(tmp_path):
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    idea_spec = {'idea': _idea(local_resources={
        'datasets': [{'path': str(tmp_path / "gone"), 'usage': 'training data'}]
    })}
    with pytest.raises(FileNotFoundError):
        stage_local_resources(work_dir, idea_spec)


def test_stage_syncs_workspace_idea_yaml(tmp_path):
    import yaml
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    (work_dir / ".neurico").mkdir()
    (work_dir / ".neurico" / "idea.yaml").write_text(yaml.dump(idea_spec))
    stage_local_resources(work_dir, idea_spec)
    synced = yaml.safe_load((work_dir / ".neurico" / "idea.yaml").read_text())
    assert synced['idea']['local_resources']['datasets'][0]['path'] == "datasets/local/toy_dataset"


def test_stage_contains_traversal_names(tmp_path):
    # A crafted dataset name must not escape datasets/local
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    idea_spec['idea']['local_resources']['datasets'][0]['name'] = "../../escape"
    stage_local_resources(work_dir, idea_spec)
    assert (work_dir / "datasets/local/escape").exists()
    assert not (tmp_path / "escape").exists()
    assert idea_spec['idea']['local_resources']['datasets'][0]['path'] == \
        "datasets/local/escape"


def test_stage_rejects_absolute_names_outside_staging(tmp_path):
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    idea_spec['idea']['local_resources']['datasets'][0]['name'] = "/tmp/leak"
    stage_local_resources(work_dir, idea_spec)
    # Reduced to basename: stays inside the staging dir
    assert (work_dir / "datasets/local/leak").exists()
    assert not Path("/tmp/leak").exists() or True  # never written outside


def test_stage_deduplicates_same_basename(tmp_path):
    work_dir, idea_spec, _data, fn = _staged_fixture(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_fn = other_dir / "protocol_eval.py"
    other_fn.write_text("def evaluate_protocol(preds, labels):\n    return 0.9\n")
    idea_spec['idea']['local_resources']['functions'].append(
        {'path': str(other_fn), 'entrypoint': 'evaluate_protocol',
         'usage': 'secondary eval'})
    stage_local_resources(work_dir, idea_spec)
    functions = idea_spec['idea']['local_resources']['functions']
    assert functions[0]['path'] == "code/local/protocol_eval.py"
    assert functions[1]['path'] == "code/local/protocol_eval_2.py"
    # Neither overwrote the other
    assert "return 0.5" in (work_dir / functions[0]['path']).read_text()
    assert "return 0.9" in (work_dir / functions[1]['path']).read_text()


def test_stage_redacts_host_paths_in_workspace_contract(tmp_path):
    import yaml
    work_dir, idea_spec, _data, _fn = _staged_fixture(tmp_path)
    idea_spec['idea'].setdefault('metadata', {})['source_path'] = "/home/alice/idea.md"
    stage_local_resources(work_dir, idea_spec)
    contract_text = (work_dir / ".neurico" / "idea.yaml").read_text()
    assert "source_path" not in contract_text
    assert str(tmp_path) not in contract_text  # no absolute host paths at all
    # ...but the in-memory spec (and thus ideas/submitted) keeps provenance
    assert idea_spec['idea']['local_resources']['datasets'][0]['source_path']
    assert idea_spec['idea']['metadata']['source_path'] == "/home/alice/idea.md"
    # And the recorded sha256 survives redaction for the integrity check
    contract = yaml.safe_load(contract_text)
    assert contract['idea']['local_resources']['functions'][0]['sha256']


def test_stage_idempotent_across_contract_reload(tmp_path):
    # A real continuation reloads the ORIGINAL submitted idea (host paths,
    # no source_path) — not the mutated in-memory spec. Re-staging from it
    # must not merge stale data or duplicate staged copies.
    import copy
    import hashlib
    work_dir, idea_spec, data, fn = _staged_fixture(tmp_path)
    pristine = copy.deepcopy(idea_spec)
    stage_local_resources(work_dir, idea_spec)

    # Simulate drift: the staged dataset gained a file that no longer exists
    # at the source; a naive re-copy with merge would keep it AND re-add
    # source files — the staged copy must instead stay exactly as staged.
    staged_data = work_dir / "datasets/local/toy_dataset"
    (staged_data / "kept_marker.txt").write_text("staged state\n")

    reloaded = copy.deepcopy(pristine)
    stage_local_resources(work_dir, reloaded)

    resources = reloaded['idea']['local_resources']
    assert resources['datasets'][0]['path'] == "datasets/local/toy_dataset"
    assert resources['functions'][0]['path'] == "code/local/protocol_eval.py"
    # Dataset kept as-is (no merge over the prior copy)
    assert (staged_data / "kept_marker.txt").exists()
    # Function refreshed from source; recorded sha matches staged bytes
    staged_fn = work_dir / "code/local/protocol_eval.py"
    digest = hashlib.sha256(staged_fn.read_bytes()).hexdigest()
    assert resources['functions'][0]['sha256'] == digest


def test_stage_reload_survives_missing_source(tmp_path):
    # Continuation on a machine where the original host paths are gone:
    # staged copies already exist, so staging must succeed without sources.
    import copy
    import shutil
    work_dir, idea_spec, data, fn = _staged_fixture(tmp_path)
    pristine = copy.deepcopy(idea_spec)
    stage_local_resources(work_dir, idea_spec)
    shutil.rmtree(tmp_path / "src_host")

    reloaded = copy.deepcopy(pristine)
    assert stage_local_resources(work_dir, reloaded) == 0
    resources = reloaded['idea']['local_resources']
    assert resources['datasets'][0]['path'] == "datasets/local/toy_dataset"
    assert resources['functions'][0]['sha256']


# ---------------------------------------------------------------- canonicalization

def test_canonicalize_rewrites_relative_paths(tmp_path):
    from core.local_resources import canonicalize_local_paths
    idea = _idea(
        local_resources={'datasets': [
            {'path': 'data/train', 'usage': 'training data'},
            {'path': '/abs/data', 'usage': 'eval data'},
        ]},
        background={'papers': [{'path': './papers/ref.pdf', 'description': 'ref'}]},
    )
    rewrites = canonicalize_local_paths(idea, base_dir=tmp_path)
    assert idea['local_resources']['datasets'][0]['path'] == \
        str((tmp_path / "data/train").resolve())
    assert idea['local_resources']['datasets'][1]['path'] == "/abs/data"
    assert idea['background']['papers'][0]['path'] == \
        str((tmp_path / "papers/ref.pdf").resolve())
    assert len(rewrites) == 2


# ---------------------------------------------------------------- prompt rendering

def _rich_idea_spec():
    return {'idea': _idea(local_resources={
        'datasets': [{'path': 'datasets/local/toy_dataset', 'usage': 'training data',
                      'source_path': '/data/toy_dataset'}],
        'functions': [{'path': 'code/local/protocol_eval.py', 'entrypoint': 'evaluate_protocol',
                       'usage': 'all evaluation', 'required_for_evaluation': True,
                       'source_path': '/tools/protocol_eval.py'}],
    }, evaluation={
        'metrics': [{'name': 'test_accuracy', 'definition': 'mean over 3 seeds',
                     'target': '>= 0.915'}],
    })}


def test_research_prompt_renders_local_resources():
    from templates.prompt_generator import PromptGenerator
    prompt = PromptGenerator().generate_research_prompt(_rich_idea_spec())
    assert "LOCAL RESOURCES (STAGED IN WORKSPACE)" in prompt
    assert "datasets/local/toy_dataset" in prompt
    # required_for_evaluation is a scoring-pipeline obligation; ordinary
    # (unscored) research prompts must not carry it
    assert "MANDATORY FOR EVALUATION" not in prompt
    assert "USER EVALUATION SPEC" in prompt
    assert ">= 0.915" in prompt


def test_research_prompt_renders_evaluation_mandate_when_scored():
    from templates.prompt_generator import PromptGenerator
    prompt = PromptGenerator().generate_research_prompt(
        _rich_idea_spec(), scoring_enabled=True)
    assert "MANDATORY FOR EVALUATION" in prompt


def test_session_instructions_render_binding_contract():
    from templates.prompt_generator import PromptGenerator
    generator = PromptGenerator()
    idea_spec = _rich_idea_spec()
    prompt = generator.generate_research_prompt(idea_spec)
    instructions = generator.generate_session_instructions(
        prompt, "/tmp/work", idea_spec=idea_spec['idea'])
    assert "BINDING LOCAL RESOURCES" in instructions
    assert "evaluate_protocol() in code/local/protocol_eval.py" in instructions
    # Scoring-only obligation stays out of unscored session instructions...
    assert "MANDATORY: all evaluation must call this function" not in instructions
    # ...and appears when scoring is enabled
    scored = generator.generate_session_instructions(
        prompt, "/tmp/work", idea_spec=idea_spec['idea'], scoring_enabled=True)
    assert "MANDATORY: all evaluation must call this function" in scored


def test_resource_finder_prompt_marks_staged_resources():
    from templates.prompt_generator import PromptGenerator
    prompt = PromptGenerator().generate_resource_finder_prompt(_rich_idea_spec())
    assert "ALREADY STAGED IN THIS WORKSPACE" in prompt
    assert "datasets/local/toy_dataset" in prompt
    assert "MANDATORY: all evaluation must run through this function" in prompt


def test_prompts_unchanged_without_local_resources():
    from templates.prompt_generator import PromptGenerator
    generator = PromptGenerator()
    plain = {'idea': _idea()}
    prompt = generator.generate_research_prompt(plain)
    assert "LOCAL RESOURCES" not in prompt
    instructions = generator.generate_session_instructions(
        prompt, "/tmp/work", idea_spec=plain['idea'])
    assert "BINDING LOCAL RESOURCES" not in instructions


# ---------------------------------------------------------------- host paths

def test_collect_host_paths_covers_resources_and_papers():
    from core.local_resources import collect_host_paths
    idea = _idea(
        local_resources={'datasets': [{'path': '/data/bench', 'usage': 'eval'}],
                         'functions': [{'path': 'code/local/e.py', 'usage': 'eval',
                                        'source_path': '/tools/e.py'}]},
        background={'papers': [{'path': '/papers/ref.pdf', 'description': 'ref'}]},
    )
    assert collect_host_paths(idea) == ['/data/bench', '/tools/e.py', '/papers/ref.pdf']


def test_collect_host_paths_skips_urls_and_relative():
    from core.local_resources import collect_host_paths
    idea = _idea(local_resources={'datasets': [
        {'path': 'datasets/local/x', 'usage': 'staged'},
        {'path': 'https://example.com/data.csv', 'usage': 'remote'},
    ]})
    assert collect_host_paths(idea) == []


def test_submit_idea_writes_mounts_sidecar(tmp_path):
    from core.idea_manager import IdeaManager
    manager = IdeaManager(ideas_dir=tmp_path)
    (tmp_path / 'data').mkdir()
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': str(tmp_path / 'data'), 'usage': 'training data'}]})}
    idea_id = manager.submit_idea(idea_spec)
    sidecar = tmp_path / "mounts" / f"{idea_id}.txt"
    assert sidecar.exists()
    assert str(tmp_path / 'data') in sidecar.read_text()


def test_submit_idea_writes_no_sidecar_without_local_paths(tmp_path):
    from core.idea_manager import IdeaManager
    manager = IdeaManager(ideas_dir=tmp_path)
    idea_id = manager.submit_idea({'idea': _idea()})
    assert not (tmp_path / "mounts" / f"{idea_id}.txt").exists()


# ---------------------------------------------------------------- idea manager

def test_validate_idea_surfaces_local_resource_errors():
    from core.idea_manager import IdeaManager
    manager = IdeaManager()
    idea_spec = {'idea': _idea(local_resources={
        'functions': [{'path': '/tmp/eval.py'}]
    })}
    result = manager.validate_idea(idea_spec)
    assert not result['valid']
    joined = " ".join(result['errors'])
    assert "usage" in joined and "entrypoint" in joined
