"""Scenario sessions: per-caller sandboxes over one shared read-only database.

DESIGN.md section 7 makes this possible -- the base DuckDB file is immutable, so a scenario is
just a pinned clock plus an overlay, and two callers can hold different hypotheticals over the
same bytes without either seeing the other's.

Everything else here is because the URL is public. Sessions live in process memory with a hard
cap and a TTL, and the cap evicts the least recently used rather than refusing new work: a demo
that stops accepting sessions because someone left twenty tabs open is a worse failure than one
that forgets an idle scenario. Nothing is persisted, so a restart drops every sandbox, which is
the correct behaviour for state that only ever existed to answer "what if".
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flightops.model.scenario import Scenario
from flightops.model.store import ObjectStore

MAX_SESSIONS = 200
SESSION_TTL = timedelta(minutes=30)
MAX_ACTIONS_PER_SESSION = 25
"""A scenario with two dozen stacked actions is not a demo, it is someone hammering the URL."""


class SessionNotFound(LookupError):
    """The session id is unknown or has expired. Distinguished so the API can say which."""


class SessionLimitReached(RuntimeError):
    """This session has applied as many actions as it is allowed."""


@dataclass
class Session:
    """One caller's scenario, and when it was last touched."""

    session_id: str
    scenario: Scenario
    created_at: datetime
    touched_at: datetime

    @property
    def action_count(self) -> int:
        return len(self.scenario.changes)


class SessionStore:
    """A bounded, expiring collection of scenarios. Not thread-safe by design; see `create`."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def create(self, clock: datetime) -> Session:
        """Open a sandbox pinned to a moment in the replayed day.

        FastAPI runs sync route handlers in a threadpool, so this is called concurrently. The
        operations that matter -- OrderedDict insert, pop, move_to_end -- are single bytecode
        operations under the GIL, and the worst case for a lost update is one evicted session
        rather than a corrupted one. A lock here would serialise every request for a guarantee
        nothing needs.
        """
        self._evict_expired()
        while len(self._sessions) >= MAX_SESSIONS:
            self._sessions.popitem(last=False)
        now = datetime.now(UTC)
        session = Session(
            session_id=secrets.token_urlsafe(12),
            scenario=Scenario(store=self._store, clock=clock),
            created_at=now,
            touched_at=now,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        self._evict_expired()
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(f"no scenario session {session_id!r}; it may have expired")
        session.touched_at = datetime.now(UTC)
        self._sessions.move_to_end(session_id)
        return session

    def guard_action_limit(self, session: Session) -> None:
        if session.action_count >= MAX_ACTIONS_PER_SESSION:
            raise SessionLimitReached(
                f"this scenario has applied {MAX_ACTIONS_PER_SESSION} actions, which is the "
                f"limit; start a new scenario to keep going"
            )

    def _evict_expired(self) -> None:
        cutoff = datetime.now(UTC) - SESSION_TTL
        expired = [key for key, session in self._sessions.items() if session.touched_at < cutoff]
        for key in expired:
            del self._sessions[key]

    def __len__(self) -> int:
        return len(self._sessions)
