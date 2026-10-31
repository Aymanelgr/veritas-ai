"""Install the Veritas workflows into the n8n container and activate them.

The workflow files in automation/n8n/ are templates: placeholders such as
__AUTOMATION_TOKEN__ are filled from .env here, so the secret never lands in Git.

Usage (from the project root, with `docker compose up -d` running):
    python scripts/setup_n8n.py
"""

import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / "automation" / "n8n"
COMPOSE = ["docker", "compose", "--project-directory", str(ROOT)]


def run(*args: str) -> str:
    result = subprocess.run([*COMPOSE, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    values = {
        "__AUTOMATION_TOKEN__": env["AUTOMATION_TOKEN"],
        # Inside the n8n container, "localhost" is the container itself;
        # host.docker.internal is Docker Desktop's name for this computer.
        "__VERITAS_API__": env.get("VERITAS_API_FROM_N8N", "http://host.docker.internal:8000"),
        "__DASHBOARD_URL__": env.get("DASHBOARD_URL", "http://localhost:5173"),
    }
    # n8n keeps its data in SQLite, which allows only one writer: while the n8n server
    # runs, the CLI gets "SQLITE_BUSY: database is locked". So stop the server, run the
    # CLI in a one-off container on the same data volume, then start the server again.
    run("stop", "n8n")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for template in sorted(WORKFLOWS.glob("*.json")):
                text = template.read_text(encoding="utf-8")
                for placeholder, value in values.items():
                    text = text.replace(placeholder, value)
                (Path(tmp) / template.name).write_text(text, encoding="utf-8")
            cli = ["run", "--rm", "--no-deps", "-v", f"{tmp}:/import", "n8n"]
            print(run(*cli, "import:workflow", "--separate", "--input=/import").strip())
            for workflow_id in ["VeritasReview001", "VeritasRemind001"]:
                print(run(*cli, "publish:workflow", f"--id={workflow_id}").strip())
    finally:
        run("start", "n8n")
    print("n8n started; webhook: http://localhost:5678/webhook/veritas-review")


if __name__ == "__main__":
    main()
