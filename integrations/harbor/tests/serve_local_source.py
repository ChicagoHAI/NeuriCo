"""Serve an unpushed source to local Harbor using its supported HTTPS transport.

For local validation only. Bind to loopback; use a temporary certificate trusted
only by the calling Git process via GIT_SSL_CAINFO. No global Git/TLS changes.
Usage: python serve_local_source.py --git-dir /repo/.git --cert cert.pem --key key.pem
"""

import argparse
import os
import ssl
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-dir", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18443)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="harbor-local-git-") as folder:
        (Path(folder) / "NeuriCo").symlink_to(args.git_dir.resolve(), target_is_directory=True)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                path, _, query = self.path.partition("?")
                if (path, query) not in {
                    ("/NeuriCo/info/refs", "service=git-upload-pack"),
                    ("/NeuriCo/git-upload-pack", ""),
                }:
                    self.send_error(404)
                    return
                environment = {
                    **os.environ,
                    "GIT_PROJECT_ROOT": folder,
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": path,
                    "QUERY_STRING": query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "REMOTE_ADDR": "127.0.0.1",
                    "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                }
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                result = subprocess.run(
                    ["git", "http-backend"],
                    input=body,
                    capture_output=True,
                    env=environment,
                    check=False,
                )
                headers, separator, payload = result.stdout.partition(b"\r\n\r\n")
                if result.returncode or not separator:
                    self.send_error(502, "Git backend failed")
                    return
                fields = [line.decode().split(":", 1) for line in headers.split(b"\r\n")]
                status = next(
                    (
                        int(value.strip().split()[0])
                        for key, value in fields
                        if key.lower() == "status"
                    ),
                    200,
                )
                self.send_response(status)
                for key, value in fields:
                    if key.lower() != "status":
                        self.send_header(key, value.strip())
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        print(f"Local read-only Git source: https://localhost:{args.port}/NeuriCo", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
