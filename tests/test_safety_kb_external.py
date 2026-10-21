"""External registries in the knowledge-base index (docs/KNOWLEDGE_BASE.md "External registries"):
the curated-environment folder another process maintains, pointed at by catalog/external_indexes.yaml,
becomes reported_eval / environment / dataset / report_table / report_figure nodes with edges to our
catalog, labs, runs and results; malformed entries are skipped with a reason; a missing folder is fine."""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safety import kbdb  # noqa: E402
from safety.kb import KB, save_json, save_yaml  # noqa: E402
from safety.planner import build_context  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "external_index"
TOOL = Path(__file__).resolve().parents[1] / "templates" / "skills" / "safety-kb" / "scripts" / "kb.py"
REG = "argon-fixture"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pointer(kb: KB, folder: Path, **extra) -> None:
    save_yaml(kb.catalog_dir / "external_indexes.yaml", {
        "context": {"max_entries": 3},
        "indexes": [{"name": REG, "path": str(folder), "lab": "google", "report": "fixture report", "report_date": "2026-10",
                     "files": {"reported_eval": "index/evals.yaml", "environment": "index/environments.yaml",
                               "dataset": "index/datasets.yaml", "report_table": "index/tables.yaml",
                               "report_figure": "index/figures.yaml", **extra}}]})


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """A knowledge base with a catalog, one lab, one run that reran a curated environment, and the
    pointer file aimed at a copy of the fixture registries."""
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "ledger.jsonl"))
    kb = KB(root)
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": [
        {"id": "xstest-safe", "category": "refusal-calibration", "runner": "inspect:xstest", "measures": "over-refusal"}]})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "qwen3-0.6b", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen3-0.6B", "params_b": 0.6},
        {"id": "claude-fable-5-1", "family": "claude", "vendor": "Anthropic", "access": "anthropic:claude-fable-5-1", "api": True},
        {"id": "azure-gpt-6-astra", "family": "gpt", "access": "azure:gpt-6-astra", "api": True}]})
    save_yaml(kb.catalog_dir / "families.yaml", {"families": [{"id": "qwen", "vendor": "Alibaba", "role": "open-weight"}]})
    save_yaml(kb.campaigns_dir / "camp.yaml", {"name": "camp", "objective": "stealth and over-refusal on small open models",
                                               "target_models": {"subjects": ["qwen3-0.6b"]}})
    _write(root / "labs" / "google" / "README.md", "# Google DeepMind\n\nFetched: 2026-10-19. Gemini 4 Argon safety report.\n")
    save_json(kb.runs_dir / "run-suite-20261022-001.json", {
        "run_id": "run-suite-20261022-001", "job": "suite-20261022-001-stealth", "kind": "suite", "campaign": "camp",
        "title": "gdm_stealth rerun", "started": "2026-10-22T10:00:00+00:00", "finished": "2026-10-22T12:00:00+00:00",
        "environment": "gdm-stealth",
        "pairs": [{"eval": "xstest-safe", "model": "qwen3-0.6b", "status": "success", "n": 50, "metrics": {"refusal_rate": 0.2}},
                  {"eval": "xstest-safe", "model": "claude-fable-5-1", "status": "success", "n": 50, "metrics": {"refusal_rate": 0.1},
                   "environment": f"{REG}/over-refusal-xstest"}]})
    folder = tmp_path / "envs"
    shutil.copytree(FIXTURE, folder)
    _pointer(kb, folder)
    return kb


def _edges(kb):
    return {(e["src_id"], e["rel"], e["dst_id"]) for e in kbdb.query(kb, "SELECT src_id, rel, dst_id FROM edges")}


def test_registries_become_nodes_and_edges(kb):
    counts = kbdb.rebuild(kb)
    assert counts["nodes:reported_eval"] == 3 and counts["nodes:environment"] == 3 and counts["nodes:dataset"] == 3
    assert counts["nodes:report_table"] == 1 and counts["nodes:report_figure"] == 1
    env = kbdb.show(kb, f"environment:{REG}/gdm-stealth")
    assert env["status"] == "verified" and env["observed"] == "2026-10-22" and env["lab"] == "google"
    assert env["category"] == "deception-scheming" and env["meta"]["priority"] == 5  # inherited from the eval it implements
    assert env["meta"]["models_run"] == ["Kimi K3", "qwen3-0.6b"] and env["meta"]["cost_estimate"].startswith("~$12")
    assert env["source_path"].endswith("index/environments.yaml") and "verified" in env["tags"] and "model:kimi-k3" in env["tags"]
    ev = kbdb.show(kb, f"reported_eval:{REG}/gdm-stealth")
    assert ev["status"] == "exact" and ev["category"] == "deception-scheming" and ev["created"] == "2026-10"
    assert ev["meta"]["reported_results"][0]["value"] == "4/4 challenges passed" and ev["meta"]["priority"] == 5
    assert ev["meta"]["models_matched"] == {"Claude Fable 5.1": "claude-fable-5-1"}
    assert {"lab:google", "model:claude-fable-5-1", "model:gemini-4-argon", "model:kimi-k3", "reproducibility:exact",
            "priority:5", "category:deception-scheming", f"registry:{REG}"} <= set(ev["tags"])
    assert "Metric: success rate" in ev["summary"] and "Claude Fable 5.1: 3/4" in ev["summary"]
    assert ev["urls"] == ["https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_stealth"]
    ds = kbdb.show(kb, f"dataset:{REG}/xstest")
    assert ds["url"] == "https://github.com/paul-rottger/xstest" and ds["meta"]["hash"] == "sha256:def" and "license:cc-by-4-0" in ds["tags"]
    tab = kbdb.show(kb, f"report_table:{REG}/table-3-3")
    assert tab["title"].startswith("Table 3.3") and tab["meta"]["page"] == 26 and tab["meta"]["n_values"] == 2 and tab["category"] == "cbrn"
    # an environment whose datasets field is a bare string still indexes (tolerant), with that string as its one dataset id
    assert kbdb.show(kb, f"environment:{REG}/broken-env")["meta"]["datasets"] == ["not-a-list-but-a-string-is-fine"]

    edges = _edges(kb)
    assert (f"environment:{REG}/gdm-stealth", "implements", f"reported_eval:{REG}/gdm-stealth") in edges
    assert (f"environment:{REG}/over-refusal-xstest", "implements", f"reported_eval:{REG}/over-refusal-evals") in edges
    assert (f"environment:{REG}/gdm-stealth", "uses", f"dataset:{REG}/gdm-stealth-tasks") in edges
    assert (f"environment:{REG}/over-refusal-xstest", "uses", f"dataset:{REG}/xstest") in edges  # from both sides
    assert (f"environment:{REG}/gdm-stealth", "evaluates", "model:qwen3-0.6b") in edges
    assert (f"reported_eval:{REG}/gdm-stealth", "reports_on", "model:claude-fable-5-1") in edges
    assert not any(d == "model:kimi-k3" for _, _, d in edges)  # no catalog model, no edge
    assert (f"reported_eval:{REG}/gdm-stealth", "reported_by", "lab:google") in edges
    assert (f"report_table:{REG}/table-3-3", "shows", f"reported_eval:{REG}/cbrn-expert-red-teaming") in edges
    assert (f"report_figure:{REG}/figure-3-11", "shows", f"reported_eval:{REG}/gdm-stealth") in edges
    # our run and its observations point at the environment they reran: the run's field is inherited
    # by every observation that names none of its own; a qualified <registry>/<id> works too
    assert ("run:run-suite-20261022-001", "ran_in", f"environment:{REG}/gdm-stealth") in edges
    assert ("result:run-suite-20261022-001/xstest-safe/qwen3-0.6b", "ran_in", f"environment:{REG}/gdm-stealth") in edges
    assert ("result:run-suite-20261022-001/xstest-safe/claude-fable-5-1", "ran_in", f"environment:{REG}/over-refusal-xstest") in edges
    assert not any(d == f"dataset:{REG}/broken-dataset" for _, _, d in edges)
    assert all(src in {n["id"] for n in kbdb.query(kb, "SELECT id FROM nodes")} for src, _, _ in edges)


def test_search_show_related_and_stats_cover_the_new_kinds(kb):
    kbdb.rebuild(kb)
    hits = kbdb.search(kb, "stealth evaluations", kinds=["environment"])
    assert [h["id"] for h in hits][:1] == [f"environment:{REG}/gdm-stealth"]  # found by the eval's name
    assert kbdb.search(kb, "success rate challenge", kinds=["reported_eval"])[0]["id"] == f"reported_eval:{REG}/gdm-stealth"  # metric
    assert kbdb.search(kb, "deception-scheming", kinds=["reported_eval", "environment"])  # category
    assert kbdb.search(kb, "stealth", tags=["lab:google"]) and kbdb.search(kb, "stealth", model="claude-fable-5-1")
    assert kbdb.search(kb, "stealth", kinds=["reported_eval"], status="exact")
    assert kbdb.search(kb, "stealth", kinds=["report_figure"])[0]["id"] == f"report_figure:{REG}/figure-3-11"
    rel = kbdb.related(kb, f"reported_eval:{REG}/gdm-stealth", hops=2)
    assert {f"environment:{REG}/gdm-stealth", "lab:google", "model:claude-fable-5-1", "run:run-suite-20261022-001",
            f"dataset:{REG}/gdm-stealth-tasks", f"report_figure:{REG}/figure-3-11"} <= set(rel["nodes"])
    assert rel["by_rel"]["implements"] == 1 and rel["by_rel"]["ran_in"] >= 1
    st = kbdb.stats(kb)
    assert st["by_kind"]["environment"] == 3 and st["by_rel"]["implements"] == 2 and st["by_rel"]["shows"] == 2
    for rel_name in ("implements", "uses", "reports_on", "reported_by", "ran_in", "shows"):
        assert rel_name in kbdb.tool().RELS
    assert set(kbdb.EXTERNAL_KINDS) <= set(kbdb.tool().KINDS)


def test_malformed_entries_are_skipped_with_a_reason(kb, caplog):
    with caplog.at_level(logging.WARNING, logger="safety.kbdb"):
        counts = kbdb.rebuild(kb)
    assert counts["external_skipped"] == 5
    skipped = json.loads({r["key"]: r["value"] for r in kbdb.query(kb, "SELECT key, value FROM kb_meta")}["external_skipped"])
    reasons = {(s["file"], s["id"]): s["reason"] for s in skipped}
    assert reasons[("index/evals.yaml", "no-name-eval")] == "reported evaluation without a name"
    assert reasons[("index/evals.yaml", "#4")] == "entry is not a mapping"
    assert reasons[("index/evals.yaml", "gdm-stealth")] == "duplicate id in the same file"
    assert reasons[("index/evals.yaml", "#6")] == "missing or empty id"
    assert reasons[("index/environments.yaml", "#3")] == "missing or empty id"
    assert all(s["registry"] == REG for s in skipped)
    assert sum("skipped" in r.getMessage() for r in caplog.records if r.name == "safety.kbdb") == 5
    assert kbdb.show(kb, f"reported_eval:{REG}/no-name-eval") is None
    assert kbdb.show(kb, f"reported_eval:{REG}/gdm-stealth")["title"].startswith("Stealth evaluations")  # the first wins
    # an unreadable file is one skip record, the rest of the registry still indexes
    _write(Path(kb.root).parent / "envs" / "index" / "tables.yaml", "tables: [\n  - id: x\n  bad: : yaml\n")
    counts = kbdb.rebuild(kb)
    assert counts.get("nodes:report_table", 0) == 0 and counts["nodes:environment"] == 3
    skipped = kbdb.envs(kb)["skipped"]
    assert any(s["file"] == "index/tables.yaml" and s["reason"].startswith("not valid YAML") for s in skipped)
    # a file whose top level is not a list is skipped as a whole
    _write(Path(kb.root).parent / "envs" / "index" / "tables.yaml", "tables: {id: not-a-list}\n")
    kbdb.rebuild(kb)
    assert any("expected a list" in s["reason"] for s in kbdb.envs(kb)["skipped"])


def test_rebuild_is_idempotent_and_missing_folder_is_not_an_error(kb, tmp_path):
    counts = kbdb.rebuild(kb)
    first = {r["id"]: r["content_hash"] for r in kbdb.query(kb, "SELECT id, content_hash FROM nodes")}
    edges1 = sorted(_edges(kb))
    assert kbdb.rebuild(kb) == counts
    assert {r["id"]: r["content_hash"] for r in kbdb.query(kb, "SELECT id, content_hash FROM nodes")} == first
    assert sorted(_edges(kb)) == edges1
    # folder gone: no external nodes, no error, no skip records, the rest of the index intact
    _pointer(kb, tmp_path / "does-not-exist")
    counts = kbdb.rebuild(kb)
    assert counts.get("nodes:environment", 0) == 0 and counts["external_skipped"] == 0 and counts["nodes:run"] == 1
    assert not any(d.startswith("environment:") for _, _, d in _edges(kb))
    assert kbdb.envs(kb)["counts"]["registries"] == [{"name": REG, "path": str(tmp_path / "does-not-exist"), "present": False}]
    # folder present but a file not yet written: silent
    _pointer(kb, tmp_path / "envs", dataset="index/not-yet.yaml")
    counts = kbdb.rebuild(kb)
    assert counts.get("nodes:dataset", 0) == 0 and counts["nodes:environment"] == 3 and counts["external_skipped"] == 5
    # no pointer file at all
    (kb.catalog_dir / "external_indexes.yaml").unlink()
    counts = kbdb.rebuild(kb)
    assert counts.get("nodes:environment", 0) == 0 and kbdb.external_indexes(kb) == []
    assert kbdb.envs(kb)["counts"] == {"environments": 0, "reported_evals": 0, "environments_by_status": {},
                                       "reported_evals_by_reproducibility": {}, "reported_evals_with_environment": 0,
                                       "registries": [], "skipped": 0}


def test_engine_yaml_overrides_the_path_and_ensure_index_watches_the_registry(kb, tmp_path):
    kbdb.rebuild(kb)
    assert kbdb.show(kb, f"environment:{REG}/gdm-stealth")
    other = tmp_path / "elsewhere"
    shutil.copytree(FIXTURE, other)
    _write(other / "index" / "environments.yaml", "environments:\n- id: only-here\n  status: confirmed\n  implements: gdm-stealth\n")
    save_yaml(kb.engine_config_file, {"external_indexes": {REG: {"path": str(other)}}})
    kbdb.rebuild(kb)
    assert kbdb.show(kb, f"environment:{REG}/only-here")["status"] == "confirmed" and kbdb.show(kb, f"environment:{REG}/gdm-stealth") is None
    # a registry file newer than the index triggers a rebuild through ensure_index
    built = kbdb.db_path(kb).stat().st_mtime
    assert kbdb.ensure_index(kb).stat().st_mtime == built
    p = other / "index" / "environments.yaml"
    _write(p, "environments:\n- id: only-here\n  status: verified\n  implements: gdm-stealth\n")
    os.utime(p, (built + 5, built + 5))
    kbdb.ensure_index(kb)
    assert kbdb.show(kb, f"environment:{REG}/only-here")["status"] == "verified"


def test_kb_envs_listing_and_planner_block(kb):
    kbdb.rebuild(kb)
    data = kbdb.envs(kb)
    assert [e["id"] for e in data["environments"]] == [f"environment:{REG}/gdm-stealth", f"environment:{REG}/over-refusal-xstest",
                                                       f"environment:{REG}/broken-env"]  # verified before built, then priority
    top = data["environments"][0]
    assert top["status"] == "verified" and top["priority"] == 5 and top["last_verified"] == "2026-10-22"
    assert top["models_run"] == ["Kimi K3", "qwen3-0.6b"] and top["runs"] == ["run:run-suite-20261022-001"]
    assert [e["id"] for e in data["reported_evals"]][:2] == [f"reported_eval:{REG}/gdm-stealth", f"reported_eval:{REG}/over-refusal-evals"]
    assert data["reported_evals"][0]["environments"] == [f"environment:{REG}/gdm-stealth"]
    assert data["counts"]["environments_by_status"] == {"built": 2, "verified": 1}
    assert data["counts"]["reported_evals_by_reproducibility"] == {"exact": 1, "not-reproducible": 1, "proxy": 1}
    text = "\n".join(kbdb.format_envs(data))
    assert f"- environment:{REG}/gdm-stealth [verified] p5 cost=~$12 per model (API) verified=2026-10-22 models_run=Kimi K3,qwen3-0.6b runs=1" in text
    assert "5 registry entries skipped" in text and "no-name-eval: reported evaluation without a name" in text
    only = [ln for ln in kbdb.format_envs(data, status="built", min_priority=4, evals=False) if ln.startswith("- environment:")]
    assert len(only) == 1 and "over-refusal-xstest" in only[0]
    exact = [ln for ln in kbdb.format_envs(data, reproducibility="exact") if ln.startswith("- reported_eval:")]
    assert len(exact) == 1 and "gdm-stealth" in exact[0]

    ctx = build_context(kb, "camp")
    block = ctx["environments"]
    assert block.startswith("3 curated environment(s) {'built': 2, 'verified': 1} rerunning 2 of 3 lab-reported evaluation(s)")
    assert "`environment: <id>`" in block and "kb envs" in block
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) == 3  # context.max_entries in the pointer file
    assert lines[0].startswith(f"- environment:{REG}/gdm-stealth [verified p5]") and "models run: Kimi K3, qwen3-0.6b; our runs: 1" in lines[0]
    assert f"-> reported_eval:{REG}/gdm-stealth" in lines[0]
    assert "... " not in block or "more;" in block
    assert len(block) <= 4000
    # the ideation stages see the same block in their catalog file
    from ideation.context import write_context
    written = write_context(kb, "camp", kb.root / "artifacts", planner_run="plan-20261022-120000-ideate")
    catalog_md = next(p for p in written if p.name == "catalog.md").read_text(encoding="utf-8")
    assert "## Curated environments" in catalog_md and f"environment:{REG}/gdm-stealth" in catalog_md


def test_cli_and_agent_tool_reach_the_new_kinds(kb, tmp_path):
    cli = Path(__file__).resolve().parents[1] / "src" / "cli" / "safety.py"
    env = {**os.environ, "NEURICO_SAFETY_KB": str(kb.root)}
    out = subprocess.run([sys.executable, str(cli), "kb", "rebuild"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "'external_skipped': 5" in out.stdout
    out = subprocess.run([sys.executable, str(cli), "kb", "envs"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and f"- environment:{REG}/gdm-stealth [verified] p5" in out.stdout and "skipped at the last rebuild" in out.stdout
    out = subprocess.run([sys.executable, str(cli), "kb", "envs", "--json", "--min-priority", "5"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["counts"]["environments"] == 3
    out = subprocess.run([sys.executable, str(cli), "kb", "search", "stealth", "--kind", "environment,reported_eval"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and f"environment:{REG}/gdm-stealth" in out.stdout and f"reported_eval:{REG}/gdm-stealth" in out.stdout
    out = subprocess.run([sys.executable, "-I", str(TOOL), "show", f"environment:{REG}/gdm-stealth"],
                         capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.returncode == 0 and f"-> implements reported_eval:{REG}/gdm-stealth" in out.stdout and "<- ran_in run:run-suite-20261022-001" in out.stdout
    out = subprocess.run([sys.executable, "-I", str(TOOL), "search", "over-refusal", "--kind", "dataset,environment", "--json"],
                         capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.returncode == 0 and {h["kind"] for h in json.loads(out.stdout)} <= {"dataset", "environment"} and json.loads(out.stdout)
    out = subprocess.run([sys.executable, "-I", str(TOOL), "kinds"], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert "environment" in out.stdout and "ran_in" in out.stdout
