"""
Core subprocess wrapper for the polymarket CLI binary.

This is the ONLY module in the SDK that calls subprocess.run.
All other modules must go through CLIWrapper to execute CLI commands.
This separation makes mocking trivial in tests and keeps the subprocess
surface area minimal and auditable.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any, List

from .exceptions import (
    AuthenticationError,
    CLIError,
    CLINotFoundError,
    NetworkError,
    ParseError,
)

logger = logging.getLogger(__name__)

# Substrings in stderr that indicate a transient / retriable failure.
_RETRYABLE_KEYWORDS = frozenset(
    [
        "connection refused",
        "connection reset",
        "timed out",
        "timeout",
        "network",
        "service unavailable",
        "503",
        "502",
        "rate limit",
        "too many requests",
        "429",
    ]
)

# Substrings in stderr that indicate an auth failure.
_AUTH_KEYWORDS = frozenset(
    [
        "unauthorized",
        "forbidden",
        "authentication",
        "api key",
        "invalid key",
        "401",
        "403",
    ]
)


def _classify_error(returncode: int, stderr: str) -> CLIError:
    """Map a raw CLI failure to the most specific exception subtype."""
    lower = stderr.lower()
    if any(kw in lower for kw in _AUTH_KEYWORDS):
        return AuthenticationError(stderr)
    if any(kw in lower for kw in _RETRYABLE_KEYWORDS):
        return NetworkError(stderr)
    return CLIError(stderr, returncode=returncode, stderr=stderr)


class CLIWrapper:
    """
    Thin subprocess wrapper around the ``polymarket`` CLI binary.

    Parameters
    ----------
    binary:
        Name or full path of the CLI binary (default: ``"polymarket"``).
    timeout:
        Per-invocation timeout in seconds.
    max_retries:
        Number of *total* attempts for retriable (NetworkError) failures.
        Set to 1 to disable retries.
    retry_delay:
        Base delay in seconds between retries.  Each subsequent retry
        doubles the delay (exponential back-off).
    extra_args:
        Additional global flags appended to every command (e.g.
        ``["--profile", "staging"]``).
    """

    def __init__(
        self,
        binary: str = "polymarket",
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        extra_args: List[str] | None = None,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.extra_args: List[str] = extra_args or []
        self._validate_binary()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, *args: str) -> Any:
        """
        Execute a CLI sub-command and return the parsed JSON response.

        ``--json`` is appended automatically so callers never need to
        include it.

        Parameters
        ----------
        *args:
            CLI arguments, e.g. ``"markets", "search", "--query", "btc"``.

        Returns
        -------
        Any
            Parsed JSON value (``dict``, ``list``, or ``None``).

        Raises
        ------
        CLINotFoundError
            Binary not on PATH.
        AuthenticationError
            Credentials missing / invalid.
        NetworkError
            Transient failure that persisted after all retries.
        CLIError
            Any other non-zero exit code.
        ParseError
            Stdout was not valid JSON.
        """
        cmd = [self.binary, *self.extra_args, *args, "--json"]
        last_exc: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                return self._execute(cmd)
            except NetworkError as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        "Transient failure (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        self.max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            except (CLIError, ParseError, AuthenticationError, CLINotFoundError):
                raise

        # All retries exhausted.
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_binary(self) -> None:
        if not shutil.which(self.binary):
            raise CLINotFoundError(
                f"polymarket CLI binary not found: '{self.binary}'. "
                "Install the binary and make sure it is on your PATH."
            )

    def _execute(self, cmd: List[str]) -> Any:
        logger.debug("Executing: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise NetworkError(
                f"CLI command timed out after {self.timeout}s"
            ) from exc
        except FileNotFoundError as exc:
            raise CLINotFoundError(
                f"Binary not found during execution: '{self.binary}'"
            ) from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            logger.error("CLI error rc=%d: %s", proc.returncode, stderr)
            raise _classify_error(proc.returncode, stderr)

        stdout = proc.stdout.strip()
        logger.debug("CLI stdout (%d chars): %s...", len(stdout), stdout[:120])

        if not stdout:
            return {}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"CLI output is not valid JSON: {stdout[:200]!r}"
            ) from exc
