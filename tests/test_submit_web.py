"""Tests for the idea-submission web form's spec builder and submit path."""

import http.client
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.idea_manager import IdeaManager
from interactive.submit_web_server import (
    SubmitWebServer,
    build_idea_spec,
    render_idea_yaml,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


MINIMAL_PAYLOAD = {
    "title": "Politeness effects on LLM answers",
    "domain": "artificial_intelligence",
    "hypothesis": "Polite prompts measurably change LLM task accuracy on benchmarks.",
}


def test_minimal_payload_builds_minimal_spec():
    spec = build_idea_spec(MINIMAL_PAYLOAD)

    assert spec == {
        "idea": {
            "title": MINIMAL_PAYLOAD["title"],
            "domain": MINIMAL_PAYLOAD["domain"],
            "hypothesis": MINIMAL_PAYLOAD["hypothesis"],
        }
    }


def test_optional_sections_are_included_only_when_populated():
    payload = dict(
        MINIMAL_PAYLOAD,
        background_description="  Context.  ",
        papers=[
            {"url": "https://arxiv.org/abs/1", "description": "relevant"},
            {"url": "", "description": ""},  # empty row is dropped
        ],
        datasets=[{"name": "GLUE", "source": "huggingface:glue"}],
        approach="Compare prompt variants.",
        steps=["one", "", "two"],
        baselines=[],
        metrics=["accuracy"],
        compute="cpu_only",
        time_limit="3600",
    )

    idea = build_idea_spec(payload)["idea"]

    assert idea["background"] == {
        "description": "Context.",
        "papers": [{"url": "https://arxiv.org/abs/1", "description": "relevant"}],
        "datasets": [{"name": "GLUE", "source": "huggingface:glue"}],
    }
    assert idea["methodology"] == {
        "approach": "Compare prompt variants.",
        "steps": ["one", "two"],
        "metrics": ["accuracy"],
    }
    assert idea["constraints"] == {"compute": "cpu_only", "time_limit": 3600}


def test_blank_optional_fields_leave_no_empty_sections():
    payload = dict(
        MINIMAL_PAYLOAD,
        background_description="",
        papers=[{"url": " ", "description": ""}],
        approach="",
        steps=[""],
        compute="",
        time_limit=None,
    )

    idea = build_idea_spec(payload)["idea"]

    assert "background" not in idea
    assert "methodology" not in idea
    assert "constraints" not in idea


def test_rendered_yaml_round_trips():
    spec = build_idea_spec(MINIMAL_PAYLOAD)

    assert yaml.safe_load(render_idea_yaml(spec)) == spec


def test_built_spec_validates_and_submits(tmp_path):
    manager = IdeaManager(tmp_path)
    spec = build_idea_spec(MINIMAL_PAYLOAD)

    validation = manager.validate_idea(spec)
    assert validation["valid"] is True

    idea_id = manager.submit_idea(spec, validate=False)
    saved = manager.get_idea(idea_id)
    assert saved["idea"]["title"] == MINIMAL_PAYLOAD["title"]
    assert saved["idea"]["metadata"]["status"] == "submitted"


def test_invalid_payload_is_rejected_by_validation(tmp_path):
    spec = build_idea_spec({"title": "x", "domain": "", "hypothesis": ""})

    validation = IdeaManager(tmp_path).validate_idea(spec)

    assert validation["valid"] is False
    assert any("hypothesis" in error for error in validation["errors"])


# ----- server integration: boot the real HTTP server and drive it like a browser


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURICO_IDEAS", str(tmp_path))
    instance = SubmitWebServer(project_root=PROJECT_ROOT, port=0)
    instance.start()
    yield instance
    instance.stop()


def _request(server, method, path, *, body=None, cookie=True, origin=None):
    connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
    headers = {}
    if cookie:
        headers["Cookie"] = f"{server.session_cookie_name}={server.access_token}"
    if origin is not None:
        headers["Origin"] = origin
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        data = raw
    return response, data


def _same_origin(server):
    return f"http://{server.host}:{server.port}"


def test_server_denies_access_without_token(server):
    response, _ = _request(server, "GET", "/", cookie=False)

    assert response.status == 403


def test_server_bootstrap_sets_session_cookie(server):
    response, _ = _request(server, "GET", f"/?token={server.access_token}", cookie=False)

    assert response.status == 302
    assert server.access_token in (response.getheader("Set-Cookie") or "")


def test_server_serves_page_and_assets_with_cookie(server):
    page, body = _request(server, "GET", "/")
    asset, _ = _request(server, "GET", "/assets/submit.js")

    assert page.status == 200 and b"submit.js" in body
    assert asset.status == 200


def test_server_context_lists_domains_and_ideas(server):
    response, context = _request(server, "GET", "/api/context")

    assert response.status == 200
    assert any(d["id"] == "machine_learning" for d in context["domains"])
    assert context["ideas"] == []


def test_server_preview_reports_validation_errors(server):
    response, preview = _request(
        server, "POST", "/api/preview",
        body={"title": "", "domain": "machine_learning", "hypothesis": "short"},
        origin=_same_origin(server),
    )

    assert response.status == 200
    assert preview["valid"] is False
    assert any("title" in error for error in preview["errors"])


def test_server_submit_writes_idea_and_returns_next_steps(server, tmp_path):
    response, result = _request(
        server, "POST", "/api/submit", body=MINIMAL_PAYLOAD, origin=_same_origin(server)
    )

    assert response.status == 201
    saved = yaml.safe_load((tmp_path / "submitted" / f"{result['idea_id']}.yaml").read_text())
    assert saved["idea"]["title"] == MINIMAL_PAYLOAD["title"]
    assert any(result["idea_id"] in step["native"] for step in result["next_steps"])

    _, context = _request(server, "GET", "/api/context")
    assert [idea["idea_id"] for idea in context["ideas"]] == [result["idea_id"]]


def test_server_submit_rejects_invalid_idea_without_writing(server, tmp_path):
    response, result = _request(
        server, "POST", "/api/submit",
        body={"title": "x", "domain": "machine_learning", "hypothesis": ""},
        origin=_same_origin(server),
    )

    assert response.status == 400
    assert result["errors"]
    assert list((tmp_path / "submitted").glob("*.yaml")) == []


def test_server_rejects_cross_origin_posts(server):
    response, _ = _request(
        server, "POST", "/api/submit", body=MINIMAL_PAYLOAD, origin="http://evil.example"
    )

    assert response.status == 403


# ----- viewing and editing existing ideas


def _submit_via_server(server):
    _, result = _request(
        server, "POST", "/api/submit", body=MINIMAL_PAYLOAD, origin=_same_origin(server)
    )
    return result["idea_id"]


def test_server_returns_idea_detail_for_viewing(server):
    idea_id = _submit_via_server(server)

    response, detail = _request(server, "GET", f"/api/ideas/{idea_id}")

    assert response.status == 200
    assert detail["editable"] is True
    assert detail["spec"]["idea"]["title"] == MINIMAL_PAYLOAD["title"]
    assert "hypothesis:" in detail["yaml"]


def test_server_view_of_missing_idea_is_404(server):
    response, _ = _request(server, "GET", "/api/ideas/nope_123")

    assert response.status == 404


def test_server_edit_updates_form_sections_and_preserves_the_rest(server, tmp_path):
    idea_id = _submit_via_server(server)
    idea_path = tmp_path / "submitted" / f"{idea_id}.yaml"
    spec = yaml.safe_load(idea_path.read_text())
    spec["idea"]["expected_outputs"] = [{"type": "report", "format": "markdown"}]
    idea_path.write_text(yaml.dump(spec, default_flow_style=False, sort_keys=False))

    edited = dict(MINIMAL_PAYLOAD, title="Edited title", steps=["new step"])
    response, result = _request(
        server, "POST", f"/api/ideas/{idea_id}", body=edited, origin=_same_origin(server)
    )

    assert response.status == 200 and result["updated"] is True
    saved = yaml.safe_load(idea_path.read_text())["idea"]
    assert saved["title"] == "Edited title"
    assert saved["methodology"] == {"steps": ["new step"]}
    assert saved["expected_outputs"] == [{"type": "report", "format": "markdown"}]
    assert saved["metadata"]["idea_id"] == idea_id
    assert "updated_at" in saved["metadata"]


def test_server_edit_preview_merges_stored_fields(server):
    idea_id = _submit_via_server(server)

    _, preview = _request(
        server, "POST", "/api/preview",
        body=dict(MINIMAL_PAYLOAD, idea_id=idea_id, title="Edited title"),
        origin=_same_origin(server),
    )

    assert preview["valid"] is True
    assert "Edited title" in preview["yaml"]
    assert "metadata:" in preview["yaml"]  # stored fields kept in the merge


def test_server_edit_is_refused_once_idea_is_in_progress(server, tmp_path):
    idea_id = _submit_via_server(server)
    IdeaManager(tmp_path).update_status(idea_id, "in_progress")

    response, result = _request(
        server, "POST", f"/api/ideas/{idea_id}",
        body=dict(MINIMAL_PAYLOAD, title="Edited title"), origin=_same_origin(server),
    )

    assert response.status == 409
    assert "in_progress" in result["errors"][0]
    detail = _request(server, "GET", f"/api/ideas/{idea_id}")[1]
    assert detail["editable"] is False
    assert detail["spec"]["idea"]["title"] == MINIMAL_PAYLOAD["title"]


def test_server_invalid_edit_does_not_touch_the_file(server, tmp_path):
    idea_id = _submit_via_server(server)
    idea_path = tmp_path / "submitted" / f"{idea_id}.yaml"
    before = idea_path.read_text()

    response, _ = _request(
        server, "POST", f"/api/ideas/{idea_id}",
        body=dict(MINIMAL_PAYLOAD, hypothesis=""), origin=_same_origin(server),
    )

    assert response.status == 400
    assert idea_path.read_text() == before
