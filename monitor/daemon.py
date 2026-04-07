"""
Background daemon manager for the Polymarket agent.

Manages start/stop/status of the autonomous agent as a background process.
Uses a PID file at ~/.polymarket/agent.pid for process tracking.

Usage (from Python)::

    from monitor.daemon import start, stop, status

    start()   # forks and starts the agent loop
    status()  # returns dict with running/pid/uptime
    stop()    # sends SIGTERM to the agent process

Usage (from CLI)::

    polymarket-sdk monitor agent start
    polymarket-sdk monitor agent stop
    polymarket-sdk monitor agent status
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_STATE_DIR = Path.home() / ".polymarket"
_PID_FILE = _STATE_DIR / "agent.pid"
_LOG_FILE = _STATE_DIR / "agent.log"


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------


def _write_pid(pid: int) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _read_pid() -> Optional[int]:
    try:
        return int(_PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid() -> None:
    try:
        _PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _is_running(pid: int) -> bool:
    """Return True if a process with *pid* is alive."""
    try:
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except (ProcessLookupError, OSError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def status() -> Dict[str, Any]:
    """Return agent process status."""
    pid = _read_pid()
    if pid is None:
        return {"running": False, "pid": None}
    if _is_running(pid):
        return {"running": True, "pid": pid, "log": str(_LOG_FILE)}
    # Stale PID file
    _remove_pid()
    return {"running": False, "pid": None, "stale_pid": pid}


def stop() -> bool:
    """
    Send SIGTERM to the agent process.

    Returns True if a signal was sent, False if the agent wasn't running.
    """
    pid = _read_pid()
    if pid is None or not _is_running(pid):
        _remove_pid()
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 5 s for clean shutdown
        for _ in range(10):
            time.sleep(0.5)
            if not _is_running(pid):
                break
        _remove_pid()
        return True
    except OSError as exc:
        logger.error("Could not stop agent (PID %d): %s", pid, exc)
        return False


def start(foreground: bool = False) -> int:
    """
    Start the autonomous agent.

    Parameters
    ----------
    foreground:
        If True, run in the current process (blocks). Otherwise fork a
        background subprocess.

    Returns
    -------
    int
        PID of the agent process.
    """
    existing = status()
    if existing["running"]:
        logger.info("Agent already running (PID %d)", existing["pid"])
        return existing["pid"]

    if foreground:
        return _run_foreground()
    else:
        return _run_background()


def _run_foreground() -> int:
    """Run the agent in the current process — blocks until stopped."""
    from .agent import PolymarketAgent
    from .config import Config

    cfg = Config.load()
    _write_pid(os.getpid())
    try:
        agent = PolymarketAgent(cfg)
        agent.run()
    finally:
        _remove_pid()
    return os.getpid()


def _run_background() -> int:
    """Fork a background subprocess running the agent."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = open(_LOG_FILE, "a")  # noqa: WPS515

    # Spawn a detached subprocess running `python -m monitor.daemon`
    proc = subprocess.Popen(
        [sys.executable, "-m", "monitor._agent_entry"],
        stdout=log_fd,
        stderr=log_fd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach from parent's process group
    )
    _write_pid(proc.pid)
    logger.info("Agent started in background (PID %d), log: %s", proc.pid, _LOG_FILE)
    return proc.pid
