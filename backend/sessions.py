"""Live-call sessions and the FIFO waiting queue (WS /ws/session/{id}).

Lifecycle of a `LiveSession`:
    created  (POST /api/session)         -> dropped if no WebSocket attaches within SESSION_IDLE_TIMEOUT_S
    queued   (WS attached, waiting)      -> position pushed on every change + every few seconds
    active   (holds one of MAX_CONCURRENT_CALLS slots; the WS handler runs the LiveCall)
    ended    (slot freed; call length recorded for the ETA)

Rules:
- FIFO by attach order. A queued visitor whose WebSocket drops keeps their place for
  RECONNECT_GRACE_S; reconnecting with the same session id resumes. While they are away the
  next *connected* visitor may take a free slot (the absentee keeps the head of the line).
- An active call ends as soon as its WebSocket drops (`finish` frees the slot immediately).
- ETA: simulated slot hand-off. Each active call is assumed to last the average measured call
  length (seeded with DEFAULT_CALL_ESTIMATE_S, capped at MAX_CALL_SECONDS); each waiting visitor
  takes the earliest free slot in turn.

Everything here runs on the event loop; no locks needed. The manager is transport-agnostic:
a session's `notify` callback receives queue updates and `promoted` is set when it gets a slot.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

log = logging.getLogger(__name__)

State = Literal["created", "queued", "active", "ended"]
NotifyFn = Callable[[dict], Awaitable[None]]


@dataclass
class LiveSession:
    id: str
    role: str
    scenario: str
    voice: str
    requested: dict = field(default_factory=dict)  # what the lobby asked for ("random" etc.)
    state: State = "created"
    created_at: float = field(default_factory=time.time)
    queued_at: float | None = None  # monotonic
    started_at: float | None = None  # monotonic
    ended_at: float | None = None
    connected: bool = False
    disconnected_at: float | None = None  # monotonic, while queued and away
    notify: NotifyFn | None = None
    promoted: asyncio.Event = field(default_factory=asyncio.Event)
    attach_seq: int = 0  # bumps on every (re)attach so a stale handler can tell it was replaced

    @property
    def queue_wait_s(self) -> float:
        if self.queued_at is None:
            return 0.0
        end = self.started_at if self.started_at is not None else time.monotonic()
        return round(end - self.queued_at, 2)


class SessionManager:
    def __init__(self, max_concurrent: int = 1, max_call_s: float = 240.0, *, reconnect_grace_s: float = 10.0,
                 idle_timeout_s: float = 60.0, default_call_s: float = 120.0, refresh_s: float = 5.0,
                 clock: Callable[[], float] = time.monotonic):
        self.max_concurrent = max(1, int(max_concurrent))
        self.max_call_s = float(max_call_s)
        self.reconnect_grace_s = reconnect_grace_s
        self.idle_timeout_s = idle_timeout_s
        self.default_call_s = default_call_s
        self.refresh_s = refresh_s
        self.clock = clock
        self.sessions: dict[str, LiveSession] = {}
        self.queue: list[str] = []  # waiting session ids, FIFO
        self.active: set[str] = set()
        self.recent_durations: deque[float] = deque(maxlen=20)
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._refresher: asyncio.Task | None = None

    # ------------------------------------------------------------ stats

    @property
    def queue_length(self) -> int:
        return len(self.queue)

    @property
    def active_calls(self) -> int:
        return len(self.active)

    def avg_call_s(self) -> float:
        est = (sum(self.recent_durations) / len(self.recent_durations)) if self.recent_durations else self.default_call_s
        return min(est, self.max_call_s)

    def position(self, sid: str) -> int:
        """1-based place in line (0 = not waiting)."""
        try:
            return self.queue.index(sid) + 1
        except ValueError:
            return 0

    def eta_s(self, sid: str) -> int:
        pos = self.position(sid)
        if pos == 0:
            return 0
        avg = self.avg_call_s()
        now = self.clock()
        free_at = []
        for aid in self.active:
            s = self.sessions.get(aid)
            elapsed = now - s.started_at if s and s.started_at is not None else 0.0
            # a call already past the average is assumed to finish soon, never past the cap
            remaining = min(max(avg - elapsed, 5.0), max(self.max_call_s - elapsed, 0.0))
            free_at.append(remaining)
        free_at += [0.0] * (self.max_concurrent - len(free_at))
        heapq.heapify(free_at)
        t = 0.0
        for _ in range(pos):
            t = heapq.heappop(free_at)
            heapq.heappush(free_at, t + avg)
        return int(round(t))

    def queue_event(self, sid: str) -> dict:
        return {"type": "queue", "position": self.position(sid), "queue_length": self.queue_length,
                "eta_s": self.eta_s(sid)}

    # ------------------------------------------------------------ lifecycle

    def create(self, role: str, scenario: str, voice: str, requested: dict | None = None) -> LiveSession:
        sid = secrets.token_urlsafe(9)
        s = LiveSession(id=sid, role=role, scenario=scenario, voice=voice, requested=requested or {})
        self.sessions[sid] = s
        self._schedule(sid, self.idle_timeout_s, self._expire_unattached)
        return s

    def get(self, sid: str) -> LiveSession | None:
        return self.sessions.get(sid)

    async def attach(self, sid: str, notify: NotifyFn) -> LiveSession:
        """A WebSocket connected for `sid`. Enqueues on first attach, resumes on reconnect.
        Raises KeyError for unknown/ended sessions, RuntimeError if the call is already active."""
        s = self.sessions.get(sid)
        if s is None or s.state == "ended":
            raise KeyError(sid)
        if s.state == "active":
            raise RuntimeError("call already in progress on another connection")
        self._cancel_timer(sid)
        s.notify = notify
        s.connected = True
        s.disconnected_at = None
        s.attach_seq += 1
        if s.state == "created":
            s.state = "queued"
            s.queued_at = self.clock()
            self.queue.append(sid)
        self._ensure_refresher()
        await self.pump()
        if s.state == "queued":
            await self.broadcast_positions()
        return s

    async def detach(self, sid: str, seq: int | None = None) -> None:
        """The WebSocket for `sid` closed. Queued: keep the place for the grace period.
        Active: the call is over (the caller should also `finish`). `seq` guards against a
        stale handler detaching a session that has since reconnected."""
        s = self.sessions.get(sid)
        if s is None or (seq is not None and seq != s.attach_seq):
            return
        s.connected = False
        s.notify = None
        if s.state == "queued":
            s.disconnected_at = self.clock()
            self._schedule(sid, self.reconnect_grace_s, self._expire_disconnected)
        elif s.state == "active":
            await self.finish(sid)
        elif s.state == "created":
            self._schedule(sid, self.idle_timeout_s, self._expire_unattached)

    async def finish(self, sid: str) -> None:
        """Call over: free the slot, record its length, promote the next visitor."""
        s = self.sessions.get(sid)
        if s is None or s.state == "ended":
            return
        was_active = s.state == "active"
        s.state = "ended"
        s.ended_at = self.clock()
        if was_active and s.started_at is not None:
            self.recent_durations.append(max(1.0, s.ended_at - s.started_at))
        self.active.discard(sid)
        if sid in self.queue:
            self.queue.remove(sid)
        self._cancel_timer(sid)
        # keep the record briefly (late GETs / reconnect attempts get a clean error), then forget it
        self._schedule(sid, 300.0, lambda x: self.sessions.pop(x, None))
        await self.pump()
        await self.broadcast_positions()

    async def remove(self, sid: str) -> None:
        """Drop a queued/created session (grace or idle timeout expired, or explicit cancel)."""
        s = self.sessions.get(sid)
        if s is None:
            return
        if s.state == "active":
            await self.finish(sid)
            return
        if sid in self.queue:
            self.queue.remove(sid)
        s.state = "ended"
        self.sessions.pop(sid, None)
        self._cancel_timer(sid)
        await self.pump()
        await self.broadcast_positions()

    async def pump(self) -> None:
        """Promote connected visitors from the head of the line into free slots."""
        while len(self.active) < self.max_concurrent:
            nxt = next((sid for sid in self.queue if self.sessions[sid].connected), None)
            if nxt is None:
                return
            self.queue.remove(nxt)
            s = self.sessions[nxt]
            s.state = "active"
            s.started_at = self.clock()
            self.active.add(nxt)
            s.promoted.set()
            log.info("session %s promoted (%s/%s active, %s waiting)", nxt, len(self.active),
                     self.max_concurrent, len(self.queue))

    async def broadcast_positions(self) -> None:
        for sid in list(self.queue):
            s = self.sessions.get(sid)
            if s is None or not s.connected or s.notify is None:
                continue
            try:
                await s.notify(self.queue_event(sid))
            except Exception:
                log.debug("queue notify failed for %s", sid, exc_info=True)

    # ------------------------------------------------------------ timers

    def _schedule(self, sid: str, delay: float, fn: Callable[[str], object]) -> None:
        self._cancel_timer(sid)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # created outside a loop (sync tests): no timers

        def fire() -> None:
            self._timers.pop(sid, None)
            r = fn(sid)
            if asyncio.iscoroutine(r):
                loop.create_task(r)

        self._timers[sid] = loop.call_later(delay, fire)

    def _cancel_timer(self, sid: str) -> None:
        h = self._timers.pop(sid, None)
        if h is not None:
            h.cancel()

    async def _expire_unattached(self, sid: str) -> None:
        s = self.sessions.get(sid)
        if s is not None and s.state == "created":
            log.info("session %s never connected; dropping", sid)
            await self.remove(sid)

    async def _expire_disconnected(self, sid: str) -> None:
        s = self.sessions.get(sid)
        if s is not None and s.state == "queued" and not s.connected:
            log.info("session %s did not reconnect within %.0fs; leaving the queue", sid, self.reconnect_grace_s)
            await self.remove(sid)

    def _ensure_refresher(self) -> None:
        if self.refresh_s <= 0 or (self._refresher is not None and not self._refresher.done()):
            return

        async def loop() -> None:
            while self.queue:
                await asyncio.sleep(self.refresh_s)
                await self.broadcast_positions()

        self._refresher = asyncio.get_running_loop().create_task(loop())
