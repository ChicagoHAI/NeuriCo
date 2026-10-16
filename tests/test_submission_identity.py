"""New submissions own independent records, even when titles and clocks match."""

import copy
import builtins
from contextlib import redirect_stdout
from datetime import datetime
import io
import multiprocessing
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import idea_manager
from core.idea_manager import IdeaManager


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 2, 3, 4, 5, tzinfo=tz)


def _spec(marker, resource=None):
    idea = {
        "title": "Same research title",
        "domain": "machine_learning",
        "hypothesis": f"Independent hypothesis for submission {marker}.",
        "metadata": {"source": marker},
    }
    if resource is not None:
        idea["local_resources"] = {
            "datasets": [{"path": str(resource), "usage": "Evaluate this submission"}]
        }
    return {"idea": idea}


@pytest.mark.parametrize("identical", [False, True], ids=["different-content", "identical-repeat"])
def test_same_title_in_same_second_keeps_every_new_submission(tmp_path, monkeypatch, identical):
    monkeypatch.setattr(idea_manager, "datetime", FrozenDateTime)
    manager = IdeaManager(tmp_path)
    specs = [_spec("first", tmp_path / "first.csv"), _spec("second", tmp_path / "second.csv")]
    if identical:
        specs[1] = copy.deepcopy(specs[0])

    ids = [manager.submit_idea(copy.deepcopy(spec)) for spec in specs]

    assert len(set(ids)) == 2
    assert {row["idea_id"] for row in manager.list_ideas()} == set(ids)
    for idea_id, original in zip(ids, specs):
        stored = manager.get_idea(idea_id)["idea"]
        assert stored["hypothesis"] == original["idea"]["hypothesis"]
        assert stored["metadata"]["source"] == original["idea"]["metadata"]["source"]
        assert stored["metadata"]["idea_id"] == idea_id
        assert stored["metadata"]["status"] == "submitted"
        assert stored["metadata"]["created_at"] == "2026-01-02T03:04:05"
        resource = original["idea"]["local_resources"]["datasets"][0]["path"]
        assert (tmp_path / "mounts" / f"{idea_id}.txt").read_text().splitlines() == [resource]


def test_resource_free_submission_does_not_inherit_previous_same_title_mounts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(idea_manager, "datetime", FrozenDateTime)
    manager = IdeaManager(tmp_path)
    resource = tmp_path / "first.csv"
    first_id = manager.submit_idea(_spec("with-resource", resource), validate=False)
    second_id = manager.submit_idea(_spec("without-resource"), validate=False)

    assert first_id != second_id
    first = manager.get_idea(first_id)["idea"]
    second = manager.get_idea(second_id)["idea"]
    assert first["metadata"]["source"] == "with-resource"
    assert first["local_resources"]["datasets"][0]["path"] == str(resource)
    assert second["metadata"]["source"] == "without-resource"
    assert "local_resources" not in second
    assert (tmp_path / "mounts" / f"{first_id}.txt").read_text().splitlines() == [str(resource)]
    assert not (tmp_path / "mounts" / f"{second_id}.txt").exists()
    assert {row["idea_id"] for row in manager.list_ideas()} == {first_id, second_id}


def _submit_worker(root, barrier, results, index, forced_id):
    """Top-level worker is importable under Windows' real spawn start method."""
    with redirect_stdout(io.StringIO()):
        try:
            idea_manager.datetime = FrozenDateTime
            manager = IdeaManager(Path(root))
            if forced_id:
                manager._generate_idea_id = lambda spec: forced_id
            spec = _spec(str(index), Path(root) / f"resource-{index}.csv")
            barrier.wait(timeout=30)
            results.put((index, "ok", manager.submit_idea(spec, validate=False)))
        except Exception as error:
            results.put((index, type(error).__name__, str(error)))


def _concurrent_submissions(tmp_path, forced_id=None):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(8)
    results = context.Queue()
    workers = [
        context.Process(target=_submit_worker, args=(str(tmp_path), barrier, results, i, forced_id))
        for i in range(8)
    ]
    try:
        for worker in workers:
            worker.start()
        outcomes = [results.get(timeout=45) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
        return outcomes
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)
        results.close()
        results.join_thread()


def test_eight_simultaneous_same_title_submissions_remain_complete(tmp_path):
    outcomes = _concurrent_submissions(tmp_path)
    assert all(status == "ok" for _, status, _ in outcomes), outcomes
    ids = [value for _, _, value in outcomes]
    assert len(set(ids)) == 8
    manager = IdeaManager(tmp_path)
    assert len(manager.list_ideas()) == 8
    for index, _, idea_id in outcomes:
        stored = manager.get_idea(idea_id)["idea"]
        assert stored["hypothesis"] == f"Independent hypothesis for submission {index}."
        assert stored["metadata"]["source"] == str(index)
        assert stored["metadata"]["idea_id"] == idea_id
        assert stored["metadata"]["status"] == "submitted"
        assert (tmp_path / "mounts" / f"{idea_id}.txt").read_text().splitlines() == [
            str(tmp_path / f"resource-{index}.csv")
        ]


@pytest.mark.parametrize("location", ["submitted", "in_progress", "completed", "mounts"])
@pytest.mark.parametrize(
    "with_resource", [False, True], ids=["no-resource-newcomer", "resource-newcomer"]
)
def test_collision_preserves_existing_record_and_mounts(
    tmp_path, monkeypatch, location, with_resource
):
    manager = IdeaManager(tmp_path)
    idea_id = "legacy_title_20260102_030405_1234abcd"
    directory = tmp_path / location
    directory.mkdir(exist_ok=True)
    suffix = ".txt" if location == "mounts" else ".yaml"
    existing_path = directory / f"{idea_id}{suffix}"
    existing_bytes = b"foreign artifact must remain byte-identical\n"
    existing_path.write_bytes(existing_bytes)
    monkeypatch.setattr(manager, "_generate_idea_id", lambda spec: idea_id)
    spec = _spec("new", tmp_path / "new.csv" if with_resource else None)

    with pytest.raises(FileExistsError):
        manager.submit_idea(spec, validate=False)

    assert existing_path.read_bytes() == existing_bytes
    visible = [
        p
        for status in ("submitted", "in_progress", "completed", "mounts")
        for p in (tmp_path / status).glob("*")
    ]
    assert visible == [existing_path]


def test_concurrent_forced_collision_has_one_winner_and_preserves_its_data(tmp_path):
    outcomes = _concurrent_submissions(tmp_path, forced_id="forced-collision")
    winners = [(index, value) for index, status, value in outcomes if status == "ok"]
    assert len(winners) == 1, outcomes
    assert sum(status == "FileExistsError" for _, status, _ in outcomes) == 7
    index, idea_id = winners[0]
    stored = IdeaManager(tmp_path).get_idea(idea_id)["idea"]
    assert stored["metadata"]["source"] == str(index)
    assert stored["hypothesis"] == f"Independent hypothesis for submission {index}."
    assert (tmp_path / "mounts" / f"{idea_id}.txt").read_text().splitlines() == [
        str(tmp_path / f"resource-{index}.csv")
    ]


def test_legacy_id_can_be_loaded_listed_moved_and_reopened(tmp_path):
    manager = IdeaManager(tmp_path)
    idea_id = "same_research_title_20260102_030405_1234abcd"
    spec = _spec("legacy")
    spec["idea"]["metadata"].update(
        idea_id=idea_id, status="submitted", github_repo_name="original-repo"
    )
    (tmp_path / "submitted" / f"{idea_id}.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")

    assert manager.get_idea(idea_id) == spec
    assert manager.list_ideas()[0]["idea_id"] == idea_id
    for status in ("in_progress", "completed", "in_progress"):
        assert manager.update_status(idea_id, status)
        reopened = IdeaManager(tmp_path)
        assert reopened.get_idea_path(idea_id) == tmp_path / status / f"{idea_id}.yaml"
        assert reopened.get_idea(idea_id)["idea"]["metadata"]["github_repo_name"] == "original-repo"
        assert len(reopened.list_ideas()) == 1


def test_successful_id_cannot_be_reissued_after_visible_files_are_removed(tmp_path, monkeypatch):
    manager = IdeaManager(tmp_path)
    monkeypatch.setattr(IdeaManager, "_generate_idea_id", lambda self, spec: "permanent-id")
    idea_id = manager.submit_idea(_spec("first"), validate=False)
    manager.get_idea_path(idea_id).unlink()

    with pytest.raises(FileExistsError):
        IdeaManager(tmp_path).submit_idea(_spec("second"), validate=False)


class _PartialWriteFailure:
    """A real file that fails after persisting some of its first write."""

    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, data):
        self.stream.write(data[: max(1, len(data) // 2)])
        self.stream.flush()
        raise OSError("injected partial write failure")

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _CloseFailure(_PartialWriteFailure):
    def write(self, data):
        return self.stream.write(data)

    def __exit__(self, *args):
        self.stream.__exit__(*args)
        raise OSError("injected close failure")


def _patch_file_opens(monkeypatch, intercept):
    # Path.open/write_text use io.open; plain open uses builtins.open.
    for module in (builtins, io):
        original = module.open

        def redirected(file, mode="r", *args, _original=original, **kwargs):
            return intercept(_original, file, mode, *args, **kwargs)

        monkeypatch.setattr(module, "open", redirected)


@pytest.mark.parametrize(
    "failure", ["serialization", "yaml-write", "mount-write", "yaml-close", "mount-close"]
)
def test_failed_submission_removes_partial_files_and_preserves_other_ideas(
    tmp_path, monkeypatch, capsys, failure
):
    manager = IdeaManager(tmp_path)
    prior_id = manager.submit_idea(_spec("prior", tmp_path / "prior.csv"), validate=False)
    prior_yaml = manager.get_idea_path(prior_id).read_bytes()
    prior_mounts = (tmp_path / "mounts" / f"{prior_id}.txt").read_bytes()
    monkeypatch.setattr(manager, "_generate_idea_id", lambda spec: "failed-new-id")
    capsys.readouterr()

    with monkeypatch.context() as fault:
        if failure == "serialization":

            def fail_dump(*args, **kwargs):
                raise yaml.YAMLError("injected serialization failure")

            fault.setattr(yaml, "dump", fail_dump)
            expected_error = yaml.YAMLError
        else:
            failed_path = (
                tmp_path / "submitted" / "failed-new-id.yaml"
                if failure.startswith("yaml-")
                else tmp_path / "mounts" / "failed-new-id.txt"
            )

            def failing_open(original, file, mode, *args, **kwargs):
                stream = original(file, mode, *args, **kwargs)
                if (
                    not isinstance(file, int)
                    and Path(file) == failed_path
                    and any(c in mode for c in "wax")
                ):
                    return (
                        _CloseFailure(stream)
                        if failure.endswith("close")
                        else _PartialWriteFailure(stream)
                    )
                return stream

            _patch_file_opens(fault, failing_open)
            expected_error = OSError

        with pytest.raises(expected_error):
            manager.submit_idea(_spec("failed", tmp_path / "failed.csv"), validate=False)

    output = capsys.readouterr()
    assert "success" not in (output.out + output.err).lower()

    assert not (tmp_path / "submitted" / "failed-new-id.yaml").exists()
    assert not (tmp_path / "mounts" / "failed-new-id.txt").exists()
    assert manager.get_idea_path(prior_id).read_bytes() == prior_yaml
    assert (tmp_path / "mounts" / f"{prior_id}.txt").read_bytes() == prior_mounts
    assert [item["idea_id"] for item in manager.list_ideas()] == [prior_id]

    retry_id = manager.submit_idea(_spec("retry", tmp_path / "retry.csv"), validate=False)
    assert retry_id == "failed-new-id"
    assert manager.get_idea(retry_id)["idea"]["metadata"]["source"] == "retry"
    assert (tmp_path / "mounts" / f"{retry_id}.txt").read_text().splitlines() == [
        str(tmp_path / "retry.csv")
    ]


@pytest.mark.parametrize("artifact", ["yaml", "mounts"])
def test_artifact_created_after_occupancy_check_is_never_overwritten_or_cleaned(
    tmp_path, monkeypatch, artifact
):
    manager = IdeaManager(tmp_path)
    monkeypatch.setattr(manager, "_generate_idea_id", lambda spec: "racing-id")
    target = (
        tmp_path / "submitted" / "racing-id.yaml"
        if artifact == "yaml"
        else tmp_path / "mounts" / "racing-id.txt"
    )
    foreign = "Created by another writer after preflight\n"
    injected = False

    def competing_open(original, file, mode, *args, **kwargs):
        nonlocal injected
        if (
            not injected
            and not isinstance(file, int)
            and Path(file) == target
            and any(c in mode for c in "wax")
        ):
            injected = True
            with original(file, "w", encoding="utf-8") as stream:
                stream.write(foreign)
        return original(file, mode, *args, **kwargs)

    _patch_file_opens(monkeypatch, competing_open)

    with pytest.raises(FileExistsError):
        manager.submit_idea(_spec("racing", tmp_path / "resource.csv"), validate=False)

    assert injected
    assert target.read_text(encoding="utf-8") == foreign
    if artifact == "mounts":
        assert not (tmp_path / "submitted" / "racing-id.yaml").exists()
    else:
        assert not (tmp_path / "mounts" / "racing-id.txt").exists()
