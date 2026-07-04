"""Subprocess isolation harness — this module *is* the per-step security boundary.

Each pipeline step runs as its own OS process (``python -m finance_agent.agents.<name>``)
with:

* a hard wall-clock **timeout** (a hung agent, and any children it spawned, is tree-killed);
* a **trimmed environment** — only the variables an agent needs, and the
  ``ANTHROPIC_API_KEY`` ONLY for steps declaring ``needs_llm``;
* a separate address space, so a crash can't corrupt the orchestrator or sibling steps;
* strict **stdout discipline** — the payload is read from stdout, logs from stderr.

Any failure (timeout / non-zero exit / empty or non-JSON stdout) becomes a uniform
:class:`StepError`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Tuple

from .contracts import AGENT_MODULE, StepSpec

# Environment variables that are safe (and on Windows, necessary) to forward.
# SystemRoot/COMSPEC are required for the Python interpreter to start on Windows.
_ENV_ALLOWLIST = (
    "SystemRoot",
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)


class StepError(Exception):
    """A step failed in an isolated way; the pipeline stops cleanly."""

    def __init__(self, step: str, reason: str, stderr: str = ""):
        self.step = step
        self.reason = reason
        self.stderr = stderr
        super().__init__(f"[{step}] {reason}")


def _trimmed_env(project_root: str, needs_llm: bool) -> dict:
    env = {var: os.environ[var] for var in _ENV_ALLOWLIST if var in os.environ}

    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        project_root + (os.pathsep + existing_pp if existing_pp else "")
    )
    env["PYTHONIOENCODING"] = "utf-8"

    # The API key is a capability. Only LLM-capable steps ever receive it; the
    # other agents literally cannot reach Claude because the key isn't present.
    if needs_llm:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            env["ANTHROPIC_API_KEY"] = key

    return env


def _kill_tree(pid: int) -> None:
    """Kill a process and its whole tree (Windows: taskkill /T; POSIX: killpg)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
    else:  # pragma: no cover - project targets Windows, but stay portable
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run_step(
    step: StepSpec,
    envelope: dict,
    *,
    project_root: str,
    timeout: float = 30.0,
) -> Tuple[dict, str]:
    """Run one agent subprocess. Returns ``(output_payload, stderr_text)``.

    Raises :class:`StepError` on any isolated failure.
    """
    module = AGENT_MODULE.format(name=step.name)
    env = _trimmed_env(project_root, step.needs_llm)

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    start_new_session = os.name != "nt"

    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=project_root,
        env=env,
        creationflags=creationflags,
        start_new_session=start_new_session,
    )

    try:
        out, err = proc.communicate(json.dumps(envelope), timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        raise StepError(step.name, f"timed out after {timeout:.0f}s and was killed")

    if proc.returncode != 0:
        raise StepError(
            step.name,
            f"exited with code {proc.returncode}",
            stderr=(err or "").strip(),
        )

    out = (out or "").strip()
    if not out:
        raise StepError(step.name, "produced no output on stdout", stderr=(err or "").strip())

    # stdout discipline: the payload is a single JSON object. If an agent leaked any
    # extra lines, take the last non-empty one and fail loudly if it isn't JSON.
    last_line = out.splitlines()[-1].strip()
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise StepError(
            step.name,
            f"stdout was not valid JSON ({exc})",
            stderr=(err or "").strip(),
        )

    if not isinstance(payload, dict):
        raise StepError(step.name, "stdout JSON was not an object", stderr=(err or "").strip())

    return payload, (err or "").strip()
