import http.client
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interactive.channel import WebChannel
from interactive.web_server import InteractiveWebServer


def _request(connection, method, path, *, headers=None, body=None):
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    response.read()
    return response


def test_token_protected_web_server_requires_bootstrap_cookie_and_same_origin(tmp_path: Path):
    channel = WebChannel()
    server = InteractiveWebServer(
        channel=channel,
        workspace=tmp_path,
        project_root=tmp_path,
        title="HITL",
        port=0,
        host="127.0.0.1",
        access_token="test-token",
    )
    server.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    origin = f"http://127.0.0.1:{server.port}"
    try:
        assert _request(connection, "GET", "/").status == 403

        bootstrap = _request(connection, "GET", "/?token=test-token")
        assert bootstrap.status == 302
        cookie = bootstrap.getheader("Set-Cookie")
        assert cookie is not None and "HttpOnly" in cookie and "SameSite=Strict" in cookie

        assert _request(connection, "GET", "/", headers={"Cookie": cookie}).status == 200

        payload = json.dumps({"text": "hello manager"})
        assert (
            _request(
                connection,
                "POST",
                "/input",
                headers={"Content-Type": "application/json", "Cookie": cookie},
                body=payload,
            ).status
            == 403
        )
        assert (
            _request(
                connection,
                "POST",
                "/input",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie,
                    "Origin": origin,
                },
                body=payload,
            ).status
            == 204
        )
        assert channel.poll_input() == "hello manager"
    finally:
        connection.close()
        server.stop()


def test_ordinary_web_server_remains_compatible_without_access_token(tmp_path: Path):
    channel = WebChannel()
    server = InteractiveWebServer(
        channel=channel,
        workspace=tmp_path,
        project_root=tmp_path,
        title="Interactive",
        port=0,
        host="127.0.0.1",
    )
    server.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    try:
        assert _request(connection, "GET", "/").status == 200
    finally:
        connection.close()
        server.stop()
