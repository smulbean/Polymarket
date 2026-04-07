"""
JSONL-based persistent storage for the monitor system.

All live data (price snapshots, trades, lessons) is stored as newline-
delimited JSON so it is both human-readable and efficiently appendable.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".polymarket"
TRADES_FILE = DATA_DIR / "trades.jsonl"
SNAPSHOTS_FILE = DATA_DIR / "snapshots.jsonl"
LESSONS_FILE = DATA_DIR / "lessons.jsonl"
PRICES_DIR = DATA_DIR / "prices"


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRICES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Core JSONL helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_record(path: Path, record: Dict[str, Any]) -> None:
    """Append one JSON record to a JSONL file (thread-unsafe, single-process)."""
    _ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_records(path: Path) -> List[Dict[str, Any]]:
    """Read all records from a JSONL file. Returns [] if file absent."""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line %d in %s", line_no, path)
    return records


def iter_records(path: Path) -> Iterator[Dict[str, Any]]:
    """Lazily iterate records from a JSONL file."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def overwrite_records(path: Path, records: List[Dict[str, Any]]) -> None:
    """Replace the contents of a JSONL file with *records*."""
    _ensure_dirs()
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# Domain-specific helpers
# ---------------------------------------------------------------------------


def save_trade(trade_dict: Dict[str, Any]) -> None:
    """Append a trade record to the trade log."""
    if not trade_dict.get("timestamp"):
        trade_dict["timestamp"] = now_iso()
    append_record(TRADES_FILE, trade_dict)


def load_trades() -> List[Dict[str, Any]]:
    return read_records(TRADES_FILE)


def update_trade(trade_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update a trade record in-place (rewrites the whole file).

    Returns True if the trade was found and updated.
    """
    trades = load_trades()
    found = False
    for t in trades:
        if t.get("trade_id") == trade_id:
            t.update(updates)
            found = True
    if found:
        overwrite_records(TRADES_FILE, trades)
    return found


def save_snapshot(snapshot_dict: Dict[str, Any]) -> None:
    """Append a monitor snapshot to the snapshots log."""
    if not snapshot_dict.get("timestamp"):
        snapshot_dict["timestamp"] = now_iso()
    append_record(SNAPSHOTS_FILE, snapshot_dict)


def save_price_point(market_id: str, price_dict: Dict[str, Any]) -> None:
    """Append a price point to the per-market price history file."""
    if not price_dict.get("timestamp"):
        price_dict["timestamp"] = now_iso()
    safe_id = market_id.replace("/", "_").replace(":", "_")[:60]
    path = PRICES_DIR / f"{safe_id}.jsonl"
    append_record(path, price_dict)


def load_price_history(market_id: str) -> List[Dict[str, Any]]:
    """Load all recorded price points for a market."""
    safe_id = market_id.replace("/", "_").replace(":", "_")[:60]
    path = PRICES_DIR / f"{safe_id}.jsonl"
    return read_records(path)


def save_lesson(lesson_dict: Dict[str, Any]) -> None:
    """Append an extracted lesson to the lessons log."""
    if not lesson_dict.get("timestamp"):
        lesson_dict["timestamp"] = now_iso()
    append_record(LESSONS_FILE, lesson_dict)


def load_lessons() -> List[Dict[str, Any]]:
    return read_records(LESSONS_FILE)
