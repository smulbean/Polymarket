"""
Custom exception hierarchy for the Polymarket SDK.

All exceptions raised by the SDK are subclasses of PolymarketError,
making it easy for callers to catch SDK-specific errors.
"""
from __future__ import annotations


class PolymarketError(Exception):
    """Base exception for all Polymarket SDK errors."""


class CLINotFoundError(PolymarketError):
    """Raised when the polymarket CLI binary is not found on PATH."""


class CLIError(PolymarketError):
    """Raised when the CLI returns a non-zero exit code."""

    def __init__(self, message: str, returncode: int = -1, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={str(self)!r}, "
            f"returncode={self.returncode}, "
            f"stderr={self.stderr!r})"
        )


class ParseError(PolymarketError):
    """Raised when CLI output cannot be parsed (e.g. not valid JSON)."""


class MarketNotFoundError(PolymarketError):
    """Raised when a requested market does not exist."""


class OrderError(PolymarketError):
    """Raised when an order cannot be placed or cancelled."""


class AuthenticationError(PolymarketError):
    """Raised when the CLI reports an authentication/authorization failure."""


class NetworkError(PolymarketError):
    """
    Raised on transient network failures.

    This is the only exception type that triggers automatic retries in
    CLIWrapper.run().  Callers should not catch NetworkError unless they
    want to suppress retry behaviour.
    """
