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

import dataclasses
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from SSTP.subprotocol.siep.src.builder import L9Message

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


def _msg_to_dict(msg: L9Message) -> dict:
    """Serialise an L9Message to a plain dict (JSON-safe)."""
    def _conv(obj):
        if dataclasses.is_dataclass(obj):
            return {k: _conv(v) for k, v in dataclasses.asdict(obj).items()}
        if hasattr(obj, "value"):
            return obj.value
        if isinstance(obj, list):
            return [_conv(i) for i in obj]
        return obj
    return _conv(msg)


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
        self._buffer: List[Tuple[str, L9Message]] = []
        self._seq = 0

        conn = sqlite3.connect(str(db_path))
        conn.execute(_CREATE_TABLE)
        conn.commit()
        conn.close()

    def append(self, label: str, msg: L9Message) -> None:
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
            ep = msg.message.epistemic if hasattr(msg.message, "epistemic") else msg.epistemic
            siep = msg.siep_payload()
            score    = siep.grounding.contingency_score if siep else None
            verified = siep.grounding.contingency_verified if siep else None
            rows.append((
                self.run_id,
                msg.message.episode,
                self._seq,
                label,
                msg.kind.value,
                msg.subkind.value if msg.subkind else None,
                msg.actor.id if msg.actor else None,
                msg.epistemic.state.value if msg.epistemic.state else None,
                msg.epistemic.message_act.value if msg.epistemic.message_act else None,
                msg.epistemic.belief_status.value if msg.epistemic.belief_status else None,
                msg.epistemic.concept_id,
                msg.epistemic.uncertainty,
                score,
                (1 if verified else 0) if verified is not None else None,
                json.dumps(_msg_to_dict(msg)),
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
            "SELECT seq, step_label, kind, subkind, actor, state, "
            "message_act, belief_status, concept_id, uncertainty, "
            "score, verified, payload_json, ts "
            "FROM l9_messages WHERE run_id=? ORDER BY seq",
            (self.run_id,),
        ).fetchall()
        conn.close()

        messages = []
        for (seq, label, kind, subkind, actor, state,
             message_act, belief_status, concept_id, uncertainty,
             score, verified, payload_json, ts) in rows:
            messages.append({
                "seq": seq,
                "step_label": label,
                "kind": f"{kind}:{subkind}" if subkind else kind,
                "actor": actor,
                "state": state,
                "message_act": message_act,
                "belief_status": belief_status,
                "concept_id": concept_id,
                "uncertainty": uncertainty,
                "contingency_score": score,
                "contingency_verified": bool(verified) if verified is not None else None,
                "timestamp": ts,
                "l9_message": json.loads(payload_json),
            })

        output = {
            "run_id": self.run_id,
            "episode_id": messages[0]["l9_message"]["message"]["episode"] if messages else None,
            "total_messages": len(messages),
            "messages": messages,
        }
        path.write_text(json.dumps(output, indent=2))

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
