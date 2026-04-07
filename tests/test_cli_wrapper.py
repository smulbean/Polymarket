"""
Tests for polymarket_sdk.cli_wrapper.CLIWrapper.

All tests mock subprocess.run — the real CLI binary is never required.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from polymarket_sdk.cli_wrapper import CLIWrapper, _classify_error
from polymarket_sdk.exceptions import (
    AuthenticationError,
    CLIError,
    CLINotFoundError,
    NetworkError,
    ParseError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def _wrapper_with_mock_binary(mock_run: MagicMock) -> CLIWrapper:
    """Create a CLIWrapper whose binary check always passes."""
    with patch("shutil.which", return_value="/usr/local/bin/polymarket"):
        return CLIWrapper(max_retries=1, retry_delay=0)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestCLIWrapperConstruction:
    def test_raises_when_binary_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(CLINotFoundError, match="not found"):
                CLIWrapper()

    def test_accepts_custom_binary_name(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/polymarket"):
            w = CLIWrapper(binary="polymarket")
        assert w.binary == "polymarket"

    def test_default_max_retries(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/polymarket"):
            w = CLIWrapper()
        assert w.max_retries == 3


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestCLIWrapperRun:
    def test_parses_json_dict(self) -> None:
        payload = {"id": "m1", "question": "Test?"}
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc(json.dumps(payload))):
            result = w.run("markets", "get", "m1")
        assert result == payload

    def test_parses_json_list(self) -> None:
        payload = [{"id": "m1"}, {"id": "m2"}]
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc(json.dumps(payload))):
            result = w.run("markets", "list")
        assert len(result) == 2

    def test_appends_json_flag(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc("{}")) as mock_run:
            w.run("markets", "list")
        call_args = mock_run.call_args[0][0]
        assert "--json" in call_args

    def test_empty_stdout_returns_empty_dict(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc("")):
            result = w.run("markets", "list")
        assert result == {}

    def test_extra_args_prepended(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1, extra_args=["--profile", "test"])
        with patch("subprocess.run", return_value=_make_proc("{}")) as mock_run:
            w.run("markets", "list")
        cmd = mock_run.call_args[0][0]
        assert "--profile" in cmd
        assert "test" in cmd


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestCLIWrapperErrors:
    def test_raises_cli_error_on_nonzero_exit(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc("", "something broke", 1)):
            with pytest.raises(CLIError):
                w.run("markets", "list")

    def test_raises_parse_error_on_invalid_json(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", return_value=_make_proc("not json at all")):
            with pytest.raises(ParseError):
                w.run("markets", "list")

    def test_raises_auth_error_on_401_message(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch(
            "subprocess.run",
            return_value=_make_proc("", "Error 401 Unauthorized", 1),
        ):
            with pytest.raises(AuthenticationError):
                w.run("markets", "list")

    def test_raises_network_error_on_timeout(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1, timeout=5)
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="polymarket", timeout=5),
        ):
            with pytest.raises(NetworkError, match="timed out"):
                w.run("markets", "list")

    def test_raises_cli_not_found_on_file_not_found(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=1)
        with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            with pytest.raises(CLINotFoundError):
                w.run("markets", "list")

    def test_retries_on_network_error(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=3, retry_delay=0)
        with patch(
            "subprocess.run",
            return_value=_make_proc("", "connection refused", 1),
        ) as mock_run:
            with pytest.raises(NetworkError):
                w.run("markets", "list")
        # Should have tried 3 times
        assert mock_run.call_count == 3

    def test_no_retry_on_cli_error(self) -> None:
        with patch("shutil.which", return_value="/bin/pm"):
            w = CLIWrapper(max_retries=3, retry_delay=0)
        with patch(
            "subprocess.run",
            return_value=_make_proc("", "market not found", 1),
        ) as mock_run:
            with pytest.raises(CLIError):
                w.run("markets", "get", "bad_id")
        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# _classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_auth_keywords(self) -> None:
        assert isinstance(_classify_error(401, "Unauthorized"), AuthenticationError)
        assert isinstance(_classify_error(403, "Forbidden access"), AuthenticationError)

    def test_network_keywords(self) -> None:
        assert isinstance(_classify_error(1, "connection refused"), NetworkError)
        assert isinstance(_classify_error(1, "rate limit exceeded"), NetworkError)

    def test_generic_cli_error(self) -> None:
        err = _classify_error(1, "some random error")
        assert isinstance(err, CLIError)
        assert err.returncode == 1
