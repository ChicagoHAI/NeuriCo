"""No-model integration fixtures through real Harbor, including environment cleanup.

Requires Docker and the image built by Dockerfile.validation. Select a compatible
Harbor runtime (see gapbench ACP client pin). Outputs stay local; only the temporary
fixture repository receives commits. No login or provider API is used.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

parser = argparse.ArgumentParser(description="No-model Harbor lifecycle validation")
parser.add_argument("--harbor", required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--image", default="neurico-harbor-validation:local")
parser.add_argument("--port", type=int, default=18443)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
base = args.output.resolve()
base.mkdir(parents=True, exist_ok=False)
source = base / "NeuriCo"
source.mkdir()
archive = base / "source.tar"
with archive.open("wb") as out:
    subprocess.run(["git", "-C", str(root), "archive", "HEAD"], stdout=out, check=True)
subprocess.run(["tar", "-xf", str(archive), "-C", str(source)], check=True)
archive.unlink()
package = source / "integrations/harbor/neurico_harbor_agent"
for name in ["research", "agent"]:
    shutil.copyfile(
        root / f"integrations/harbor/tests/fixtures/{name}.py", package / f"fixture_{name}.py"
    )
entry = package / "run_autoresearch.py"
entry.write_text(
    entry.read_text().replace(
        'if __name__ == "__main__":\n    main()',
        'if __name__ == "__main__":\n    from .fixture_research import run_research\n    ResearchRunner.run_research = run_research\n    main()',
    )
)
manifest = source / "integrations/harbor/harbor-agent.json"
data = json.loads(manifest.read_text())
data["runtime"]["entrypoint"] = ["python", "-m", "neurico_harbor_agent.fixture_agent"]
manifest.write_text(json.dumps(data))
for git_args in [
    ("init",),
    ("add", "."),
    (
        "-c",
        "user.name=Local fixture",
        "-c",
        "user.email=fixture@localhost",
        "commit",
        "-qm",
        "No-model validation source",
    ),
]:
    subprocess.run(["git", "-C", str(source), *git_args], check=True, stdout=subprocess.DEVNULL)
sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
auth = base / "auth.json"
auth.write_text('{"tokens":{"access_token":"fixture-only-credential"}}')
auth.chmod(0o600)
for case in ["success", "failed-child", "public-failure", "timeout"]:
    task = base / case
    (task / "environment").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text(
        f"Produce /app/answer.txt containing pass. Fixture case: {case}.\n"
    )
    timeout = 10 if case == "timeout" else 60
    (task / "task.toml").write_text(f"""schema_version = "1.4"
artifacts = ["/app/answer.txt"]
[metadata]
[verifier]
timeout_sec = 30.0
[agent]
timeout_sec = {timeout}.0
[environment]
network_mode = "public"
build_timeout_sec = 120.0
os = "linux"
""")
    (task / "environment/Dockerfile").write_text(
        f'FROM {args.image}\nENV PYTHONPATH=""\nWORKDIR /app\nRUN mkdir -p /installed-agent/source && cp -a /root/.cache/uv /installed-agent/source/.uv-cache\n'
    )
    (task / "tests/test.sh").write_text(
        "#!/bin/sh\nmkdir -p /logs/verifier\nif [ -f /app/answer.txt ]; then echo 1; else echo 0; fi > /logs/verifier/reward.txt\n"
    )
    config = {
        "job_name": case,
        "jobs_dir": str(base / "jobs"),
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0},
        "tasks": [{"path": str(task)}],
        "environment": {
            "type": "docker",
            "delete": True,
            "mounts": [
                {
                    "type": "bind",
                    "source": str(auth),
                    "target": "/run/secrets/neurico-codex-auth.json",
                    "read_only": True,
                }
            ],
        },
        "agents": [
            {
                "name": "acp",
                "model_name": "openai/fixture",
                "kwargs": {
                    "source": {
                        "repo_url": f"https://localhost:{args.port}/NeuriCo",
                        "ref": sha,
                        "source_dir": ".",
                        "manifest_path": "integrations/harbor/harbor-agent.json",
                    }
                },
                "env": {
                    "NEURICO_CODEX_AUTH_FILE": "/run/secrets/neurico-codex-auth.json",
                    "NEURICO_HARBOR_WORKFLOW": "focused-managed-ordinary",
                    "NEURICO_HARBOR_PRESERVE_INTERNAL_TRACES": "1",
                    "NEURICO_HARBOR_REASONING_EFFORT": "high",
                    "NEURICO_FIXTURE_PUBLIC_FAILURE": "1" if case == "public-failure" else "0",
                },
            }
        ],
    }
    (base / f"{case}.yaml").write_text(yaml.safe_dump(config))
cert, key = base / "cert.pem", base / "key.pem"
subprocess.run(
    [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-days",
        "2",
        "-subj",
        "/CN=localhost",
        "-addext",
        "subjectAltName=DNS:localhost",
    ],
    check=True,
    capture_output=True,
)
env = dict(os.environ)
env.pop("HARBOR_ACP_SOURCE_GIT_TOKEN", None)
env["GIT_SSL_CAINFO"] = str(cert)
report = []
with (base / "source-server.log").open("w") as log:
    server = subprocess.Popen(
        [
            os.sys.executable,
            str(root / "integrations/harbor/tests/serve_local_source.py"),
            "--git-dir",
            str(source / ".git"),
            "--cert",
            str(cert),
            "--key",
            str(key),
            "--port",
            str(args.port),
        ],
        stdout=subprocess.PIPE,
        stderr=log,
        text=True,
    )
    try:
        assert server.stdout.readline().startswith("Local read-only Git source:")
        for case in ["success", "failed-child", "public-failure", "timeout"]:
            with (base / f"{case}.controller.log").open("w") as output:
                subprocess.run(
                    [args.harbor, "run", "--config", str(base / f"{case}.yaml")],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            (trial,) = list((base / "jobs" / case).glob("*/result.json"))
            result = json.loads(trial.read_text())
            (manifest,) = list(trial.parent.glob("agent/neurico/*/manifest.json"))
            evidence = json.loads(manifest.read_text())
            assert evidence["finalized"] and evidence["collection_status"] == "complete", (
                evidence.get("gaps")
            )
            assert len(evidence["invocations"]) == 2
            assert (manifest.parent / "answer.bin").read_bytes() == b"\x00fixture result"
            from hashlib import sha256

            for item in evidence["files"]:
                payload = (manifest.parent / item["path"]).read_bytes()
                assert (
                    len(payload) == item["bytes"] and sha256(payload).hexdigest() == item["sha256"]
                )
            expected = 1.0 if case in {"success", "public-failure"} else 0.0
            assert result["verifier_result"]["rewards"]["reward"] == expected
            if case == "timeout":
                assert result["exception_info"]["exception_type"] == "AgentTimeoutError"
            report.append(
                {
                    "case": case,
                    "trial": str(trial.parent.relative_to(base)),
                    "reward": expected,
                    "archive_files": len(evidence["files"]),
                    "archive_status": evidence["collection_status"],
                }
            )
            print(case, "passed", flush=True)
    finally:
        server.terminate()
        server.wait(timeout=10)
(base / "validation.json").write_text(json.dumps({"source_commit": sha, "cases": report}, indent=2))
print(base / "validation.json")
