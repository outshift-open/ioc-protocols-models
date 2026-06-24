# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Simple message store for the CIP demo — persists L9 messages to SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ai.outshift.data_model import L9

_DEFAULT_DB = Path(__file__).resolve().parents[4] / "cip_episodes.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cip_messages (
    run_id        TEXT NOT NULL,
    episode_id    TEXT NOT NULL,
    seq           INT  NOT NULL,
    step_label    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    subkind       TEXT,
    actor         TEXT,
    payload_json  TEXT NOT NULL,
    ts            TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""

_INSERT = """
INSERT INTO cip_messages
    (run_id, episode_id, seq, step_label, kind, subkind, actor, payload_json, ts)
VALUES (?,?,?,?,?,?,?,?,?)
"""


def _sender_id(msg: L9) -> str:
    return msg.header.participants.actors[0].id


class MessageStore:
    """Append-only store for L9 messages within a single CIP demo run."""

    def __init__(self, db_path: Path = _DEFAULT_DB, run_id: Optional[str] = None) -> None:
        self.run_id = run_id or str(_uuid.uuid4())
        self.db_path = db_path
        self._buffer: List[Tuple[str, L9]] = []
        self._seq = 0

        conn = sqlite3.connect(str(db_path))
        conn.execute(_CREATE_TABLE)
        conn.commit()
        conn.close()

    def append(self, label: str, msg: L9) -> None:
        """Buffer one message; call flush() to persist."""
        self._buffer.append((label, msg))

    def flush(self) -> None:
        """Write all buffered messages to the database."""
        if not self._buffer:
            return
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows = []
        for label, msg in self._buffer:
            self._seq += 1
            kind = msg.header.kind.value if hasattr(msg.header.kind, "value") else msg.header.kind
            rows.append((
                self.run_id,
                msg.header.message.episode,
                self._seq,
                label,
                kind,
                msg.header.subkind,
                _sender_id(msg),
                msg.model_dump_json(),
                ts,
            ))
        conn = sqlite3.connect(str(self.db_path))
        conn.executemany(_INSERT, rows)
        conn.commit()
        conn.close()
        self._buffer.clear()

    def write_json(self, path: Path) -> None:
        """Write the full message sequence for this run to a JSON file."""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT payload_json FROM cip_messages WHERE run_id=? ORDER BY seq",
            (self.run_id,),
        ).fetchall()
        conn.close()
        messages = [json.loads(row[0]) for row in rows]
        path.write_text(json.dumps(messages, indent=2))

    def print_table(self) -> None:
        """Print the stored sequence for this run as a formatted table."""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT seq, step_label, kind, subkind, actor "
            "FROM cip_messages WHERE run_id=? ORDER BY seq",
            (self.run_id,),
        ).fetchall()
        conn.close()

        W = 100
        print("=" * W)
        print(f"  CIP MESSAGE SEQUENCE  —  run={self.run_id[:8]}…")
        print("=" * W)
        hdr = f"  {'seq':>3}  {'step / label':<36}  {'kind':<20}  {'actor':<14}"
        print(hdr)
        print("-" * W)
        for seq, label, kind, subkind, actor in rows:
            k = f"{kind}:{subkind}" if subkind else kind
            print(f"  {seq:>3}  {label:<36}  {k:<20}  {actor or '—':<14}")
        print("=" * W)


__all__ = ["MessageStore"]
