# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
MessageStore — persists the ordered sequence of L9 messages for a SIEP episode
into the shared episodes.db SQLite database (table: l9_messages).

Schema
------
  run_id       TEXT   — unique identifier for this demo run (UUID)
  episode_id   TEXT   — L9 episode URN (shared by all messages in the episode)
  seq          INT    — 1-based message sequence number within the run
  step_label   TEXT   — human-readable step label (e.g. "1 · intent")
  kind         TEXT   — L9 kind: intent | exchange | contingency | commit
  subkind      TEXT   — optional subkind: converged | rejected | null
  actor        TEXT   — sending agent id
  state        TEXT   — epistemic state: taskwork | grounding | team_process
  message_act  TEXT   — assertion | challenge | null
  belief_status TEXT  — asserted | challenged | revised | unresolved | null
  concept_id   TEXT   — concept URI under discussion
  uncertainty  REAL   — sender confidence [0..1]
  score        REAL   — contingency_score if present
  verified     INT    — 1/0/null for contingency_verified
  payload_json TEXT   — full message serialised as JSON
  ts           TEXT   — ISO-8601 UTC timestamp of insertion
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ioc_l9.src import L9
from SSTP.subprotocol.siep.src.siep_payload import SIEPMessagePayload

_DEFAULT_DB = Path(__file__).resolve().parents[4] / "episodes.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS l9_messages (
    run_id        TEXT NOT NULL,
    episode_id    TEXT NOT NULL,
    seq           INT  NOT NULL,
    step_label    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    subkind       TEXT,
    actor         TEXT,
    state         TEXT,
    message_act   TEXT,
    belief_status TEXT,
    concept_id    TEXT,
    uncertainty   REAL,
    score         REAL,
    verified      INT,
    payload_json  TEXT NOT NULL,
    ts            TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""

_INSERT = """
INSERT INTO l9_messages
    (run_id, episode_id, seq, step_label, kind, subkind,
     actor, state, message_act, belief_status, concept_id,
     uncertainty, score, verified, payload_json, ts)
VALUES
    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _sender_id(msg: L9) -> str:
    return msg.header.actors.actors[0].id


def _siep_payload(msg: L9) -> SIEPMessagePayload:
    return SIEPMessagePayload.model_validate(msg.payload.data)


class MessageStore:
    """
    Append-only store for L9 messages within a single demo run.

    Usage::

        store = MessageStore()
        store.append("1 · intent", msg)
        store.flush()          # write all buffered rows to SQLite
        store.print_table()    # pretty-print stored sequence
    """

    def __init__(self, db_path: Path = _DEFAULT_DB, run_id: Optional[str] = None) -> None:
        import uuid as _uuid

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
            context = msg.header.context
            epistemic = context.epistemic if context else None
            siep = _siep_payload(msg)
            score = siep.grounding.contingency_score
            verified = siep.grounding.contingency_verified
            rows.append((
                self.run_id,
                msg.header.message.episode,
                self._seq,
                label,
                msg.header.kind,
                msg.header.subkind,
                _sender_id(msg),
                epistemic.state if epistemic else None,
                epistemic.message_act if epistemic else None,
                epistemic.belief_status if epistemic else None,
                epistemic.concept_id if epistemic else None,
                epistemic.uncertainty if epistemic else None,
                score,
                (1 if verified else 0) if verified is not None else None,
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
            "SELECT seq, step_label, kind, subkind, actor, ts, payload_json "
            "FROM l9_messages WHERE run_id=? ORDER BY seq",
            (self.run_id,),
        ).fetchall()
        conn.close()

        messages = [json.loads(payload_json) for (_, _, _, _, _, _, payload_json) in rows]
        path.write_text(json.dumps(messages, indent=2))

    def print_table(self) -> None:
        """Print the stored sequence for this run as a formatted table."""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT seq, step_label, kind, subkind, actor, state, score, verified "
            "FROM l9_messages WHERE run_id=? ORDER BY seq",
            (self.run_id,),
        ).fetchall()
        conn.close()

        W = 100
        print("=" * W)
        print(f"  L9 MESSAGE SEQUENCE  —  run={self.run_id[:8]}…")
        print("=" * W)
        hdr = f"  {'seq':>3}  {'step / label':<32}  {'kind':<12}  {'actor':<14}  {'state':<14}  {'score':>6}  {'✓'}"
        print(hdr)
        print("-" * W)
        for seq, label, kind, subkind, actor, state, score, verified in rows:
            k = f"{kind}:{subkind}" if subkind else kind
            s = f"{score:.3f}" if score is not None else "  —  "
            v = ("✓" if verified else "✗") if verified is not None else "—"
            print(f"  {seq:>3}  {label:<32}  {k:<12}  {actor or '—':<14}  {state or '—':<14}  {s:>6}  {v}")
        print("=" * W)


__all__ = ["MessageStore"]
