"""Start the local model server on demand.

The digest cannot run without the local OpenAI-compatible server. Rather than making the
operator remember a separate command, the CLI can check /health and, when the server is
down and autostart is enabled, launch the project's own start script and wait for health.

Safety:
  * off by default (`OR_MODEL_AUTOSTART=0`);
  * only the project script is launched, never an arbitrary command;
  * only on Windows, where the script exists;
  * a failed start never falls through to analyzing with a dead endpoint — the run exits
    with a clear message instead of producing 30 identical connection errors.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

START_SCRIPT = Path("deploy") / "windows" / "start-model.ps1"


def health_ok(base_url: str, timeout: int = 3) -> bool:
    url = base_url.rstrip("/")
    # Accept both http://host:port and http://host:port/v1.
    if url.endswith("/v1"):
        url = url[:-3]
    try:
        with urlopen(Request(f"{url}/health", headers={"User-Agent": "OpportunityRadar/0.1"}), timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
            return isinstance(payload, dict) and payload.get("status") == "ok"
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def ensure_model(settings, poll_seconds: float = 3.0, log=None) -> tuple[bool, str]:
    """Return (ready, detail). Starts the documented script only when allowed."""
    log = log or logging.getLogger(__name__)
    if health_ok(settings.llm_base_url):
        return True, "model already healthy"
    if not getattr(settings, "model_autostart", False):
        return False, "model is not reachable and OR_MODEL_AUTOSTART is off"
    if os.name != "nt":
        return False, "autostart is only implemented for the Windows start script"
    script = START_SCRIPT.resolve()
    if not script.exists():
        return False, f"start script missing: {START_SCRIPT}"

    log.warning("Local model is down; starting %s", START_SCRIPT)
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(script.parents[2]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, f"could not launch the model script: {type(exc).__name__}"

    deadline = time.monotonic() + max(30, int(getattr(settings, "model_start_timeout", 600)))
    while time.monotonic() < deadline:
        if health_ok(settings.llm_base_url):
            return True, "model started and healthy"
        time.sleep(poll_seconds)
    return False, f"model did not become healthy within {getattr(settings, 'model_start_timeout', 600)}s"
