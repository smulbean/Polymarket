"""
Entry point for the background agent subprocess.

Invoked by daemon._run_background() as:
    python -m monitor._agent_entry
"""
from __future__ import annotations

import logging
import os
import signal
import sys


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    from monitor.agent import PolymarketAgent
    from monitor.config import Config
    from monitor.daemon import _remove_pid, _write_pid

    _write_pid(os.getpid())

    def _handle_sigterm(signum: int, frame: object) -> None:
        logger.info("Received SIGTERM — shutting down agent")
        _remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    cfg = Config.load()
    agent = PolymarketAgent(cfg)
    try:
        agent.run()
    except Exception as exc:
        logger.error("Agent crashed: %s", exc, exc_info=True)
    finally:
        _remove_pid()


if __name__ == "__main__":
    main()
