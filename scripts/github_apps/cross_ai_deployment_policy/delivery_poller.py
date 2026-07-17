"""Fail-closed outbound reconciliation for failed GitHub App webhook deliveries."""

from __future__ import annotations

import logging
import math
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from .errors import PolicyError, reject
from .github import GitHubHookDeliveryReader, HookDeliveryPage
from .ledger import ObserveLedger
from .timeutil import parse_utc
from .webhook import (
    DeploymentProtectionRequest,
    parse_deployment_protection_delivery,
)


LOGGER = logging.getLogger("cross_ai_deployment_policy.delivery_poller")
TARGET_EVENT = "deployment_protection_rule"
TARGET_ACTION = "requested"
MAX_PAGES = 5
MAX_CANDIDATES = 100


class PolledDeliveryProcessor(Protocol):
    def process_polled(self, request: DeploymentProtectionRequest) -> bool: ...


@dataclass(frozen=True)
class DeliveryItem:
    api_delivery_id: int
    guid: str
    delivered_at: datetime
    redelivery: bool
    status: str
    status_code: int
    event: str
    action: str | None
    installation_id: int | None
    repository_id: int | None


def _integer(value: object, field: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", f"{field} must be an integer")
    if positive and value < 1:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", f"{field} must be positive")
    return value


def _nullable_positive(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field, positive=True)


def _item(value: dict[str, Any]) -> DeliveryItem:
    required = {
        "id",
        "guid",
        "delivered_at",
        "redelivery",
        "duration",
        "status",
        "status_code",
        "event",
        "action",
        "installation_id",
        "repository_id",
    }
    if not required.issubset(value):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery list item is incomplete")
    api_delivery_id = _integer(value["id"], "delivery.id", positive=True)
    guid = value["guid"]
    if not isinstance(guid, str) or len(guid) != 36:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.guid is invalid")
    delivered_at = parse_utc(value["delivered_at"], "delivery.delivered_at")
    redelivery = value["redelivery"]
    if not isinstance(redelivery, bool):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.redelivery is invalid")
    duration = value["duration"]
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or not 0 <= duration <= 600
    ):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.duration is invalid")
    status = value["status"]
    event = value["event"]
    action = value["action"]
    if not isinstance(status, str) or not 1 <= len(status) <= 500:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.status is invalid")
    if not isinstance(event, str) or not 1 <= len(event) <= 100:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.event is invalid")
    if action is not None and (not isinstance(action, str) or len(action) > 100):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery.action is invalid")
    return DeliveryItem(
        api_delivery_id=api_delivery_id,
        guid=guid.lower(),
        delivered_at=delivered_at,
        redelivery=redelivery,
        status=status,
        status_code=_integer(value["status_code"], "delivery.status_code"),
        event=event,
        action=action,
        installation_id=_nullable_positive(
            value["installation_id"], "delivery.installation_id"
        ),
        repository_id=_nullable_positive(value["repository_id"], "delivery.repository_id"),
    )


def _cross_check_detail(
    *,
    item: DeliveryItem,
    detail: dict[str, Any],
    expected_webhook_url: str,
) -> object:
    exact = {
        "id": item.api_delivery_id,
        "guid": item.guid,
        "redelivery": item.redelivery,
        "status": item.status,
        "status_code": item.status_code,
        "event": item.event,
        "action": item.action,
        "installation_id": item.installation_id,
        "repository_id": item.repository_id,
    }
    for field, expected in exact.items():
        actual = detail.get(field)
        if field == "guid" and isinstance(actual, str):
            actual = actual.lower()
        if actual != expected:
            reject(
                "GITHUB_DELIVERY_LIST_DETAIL_MISMATCH",
                f"delivery list/detail field {field} differs",
            )
    if parse_utc(detail.get("delivered_at"), "deliveryDetail.delivered_at") != item.delivered_at:
        reject(
            "GITHUB_DELIVERY_LIST_DETAIL_MISMATCH",
            "delivery list/detail timestamp differs",
        )
    if detail.get("url") != expected_webhook_url:
        reject("GITHUB_DELIVERY_TARGET_MISMATCH", "delivery target URL differs")
    request = detail.get("request")
    if not isinstance(request, dict) or set(request) != {"headers", "payload"}:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery request shape is invalid")
    headers = request.get("headers")
    payload = request.get("payload")
    if headers is not None and not isinstance(headers, dict):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery request headers are invalid")
    if not isinstance(payload, dict):
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery request payload is invalid")
    response = detail.get("response")
    if not isinstance(response, dict) or set(response) != {"headers", "payload"}:
        reject("GITHUB_DELIVERY_SHAPE_INVALID", "delivery response shape is invalid")
    return payload


class DeliveryPoller:
    def __init__(
        self,
        *,
        reader: GitHubHookDeliveryReader,
        processor: PolledDeliveryProcessor,
        ledger: ObserveLedger,
        expected_webhook_url: str,
        expected_installation_id: int,
        expected_repository_id: int,
        allowed_api_origins: tuple[str, ...] = ("https://api.github.com",),
        interval_seconds: float = 30.0,
        jitter_seconds: float = 5.0,
        max_delivery_age: timedelta = timedelta(minutes=15),
        overlap: timedelta = timedelta(minutes=5),
        stale_after: timedelta = timedelta(minutes=2),
        now: Callable[[], datetime] | None = None,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        if interval_seconds < 30 or not 0 <= jitter_seconds <= 5:
            reject(
                "POLLER_INTERVAL_INVALID",
                "delivery poll interval must be at least 30s with at most 5s jitter",
            )
        if expected_installation_id < 1 or expected_repository_id < 1:
            reject("POLLER_SCOPE_INVALID", "poller installation/repository scope is invalid")
        webhook_target = urlsplit(expected_webhook_url)
        try:
            webhook_port = webhook_target.port
        except ValueError:
            reject("POLLER_CONFIG_INVALID", "webhook target port is invalid")
        if (
            webhook_target.scheme != "https"
            or webhook_target.hostname is None
            or webhook_target.username is not None
            or webhook_target.password is not None
            or webhook_target.query
            or webhook_target.fragment
            or webhook_port not in {None, 443}
            or not webhook_target.path.startswith("/")
            or len(expected_webhook_url) > 500
            or max_delivery_age <= timedelta(0)
            or overlap <= timedelta(0)
            or stale_after <= timedelta(seconds=interval_seconds + jitter_seconds)
        ):
            reject("POLLER_CONFIG_INVALID", "delivery poller configuration is invalid")
        self.reader = reader
        self.processor = processor
        self.ledger = ledger
        self.expected_webhook_url = expected_webhook_url
        self.expected_installation_id = expected_installation_id
        self.expected_repository_id = expected_repository_id
        self.allowed_api_origins = allowed_api_origins
        self.interval_seconds = interval_seconds
        self.jitter_seconds = jitter_seconds
        self.max_delivery_age = max_delivery_age
        self.overlap = overlap
        self.stale_after = stale_after
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._jitter = jitter or random.uniform
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._healthy = False
        self._last_success: datetime | None = None

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None:
                reject("POLLER_ALREADY_STARTED", "delivery poller is already started")
            self._thread = threading.Thread(
                target=self._loop,
                name="cross-ai-delivery-poller",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=10)
        with self._state_lock:
            self._healthy = False

    def ready(self) -> bool:
        with self._state_lock:
            healthy = self._healthy
            last_success = self._last_success
        return (
            healthy
            and last_success is not None
            and self._now() - last_success <= self.stale_after
        )

    def _cutoff(self, now: datetime) -> datetime:
        cutoff = now - self.max_delivery_age
        state = self.ledger.poller_state()
        if state.high_water_delivered_at is not None:
            overlap_cutoff = (
                parse_utc(
                    state.high_water_delivered_at,
                    "pollerState.high_water_delivered_at",
                )
                - self.overlap
            )
            cutoff = max(cutoff, overlap_cutoff)
        return cutoff

    def _collect(self, *, now: datetime) -> tuple[Any, list[DeliveryItem]]:
        cycle = self.reader.cycle()
        cutoff = self._cutoff(now)
        cursor: str | None = None
        items: list[DeliveryItem] = []
        seen_ids: set[int] = set()
        previous: tuple[datetime, int] | None = None
        for page_number in range(1, MAX_PAGES + 1):
            page: HookDeliveryPage = cycle.list_deliveries(cursor=cursor)
            page_has_old = False
            for raw in page.items:
                parsed = _item(raw)
                order = (parsed.delivered_at, parsed.api_delivery_id)
                if previous is not None and order > previous:
                    reject(
                        "GITHUB_DELIVERY_ORDER_INVALID",
                        "delivery API order is not newest-first",
                    )
                previous = order
                if parsed.api_delivery_id in seen_ids:
                    reject("GITHUB_DELIVERY_DUPLICATE", "delivery API repeated an ID")
                seen_ids.add(parsed.api_delivery_id)
                if parsed.delivered_at > now + timedelta(seconds=30):
                    reject("GITHUB_DELIVERY_FUTURE", "delivery timestamp is in the future")
                if parsed.delivered_at < cutoff:
                    page_has_old = True
                    continue
                items.append(parsed)
            cursor = page.next_cursor
            if cursor is None or page_has_old:
                return cycle, items
            if page_number == MAX_PAGES:
                reject("GITHUB_DELIVERY_WINDOW_TRUNCATED", "delivery window exceeds page cap")
        reject("GITHUB_DELIVERY_WINDOW_TRUNCATED", "delivery pagination did not terminate")

    def poll_once(self) -> int:
        now = self._now()
        cycle, listed = self._collect(now=now)
        candidates = [
            item
            for item in listed
            if item.event == TARGET_EVENT
            and item.action == TARGET_ACTION
            and item.installation_id == self.expected_installation_id
            and item.repository_id == self.expected_repository_id
            and not 200 <= item.status_code <= 399
        ]
        if len(candidates) > MAX_CANDIDATES:
            reject("GITHUB_DELIVERY_CANDIDATE_LIMIT", "too many delivery candidates")
        processed = 0
        for item in sorted(
            candidates,
            key=lambda candidate: (candidate.delivered_at, candidate.api_delivery_id),
        ):
            detail = cycle.delivery(item.api_delivery_id)
            payload = _cross_check_detail(
                item=item,
                detail=detail,
                expected_webhook_url=self.expected_webhook_url,
            )
            request = parse_deployment_protection_delivery(
                payload=payload,
                delivery_id=item.guid,
                allowed_api_origins=self.allowed_api_origins,
            )
            if (
                request.installation_id != self.expected_installation_id
                or request.repository_id != self.expected_repository_id
            ):
                reject("GITHUB_DELIVERY_PAYLOAD_SCOPE_MISMATCH", "payload scope differs")
            if not self.processor.process_polled(request):
                reject(
                    "POLLER_CALLBACK_NOT_SUCCEEDED",
                    "GitHub decision callback was not accepted",
                )
            self.ledger.advance_poller_after_callback(
                request=request,
                api_delivery_id=item.api_delivery_id,
                delivered_at=item.delivered_at,
                recorded_at=now,
            )
            processed += 1
        self.ledger.mark_poller_success(recorded_at=now)
        return processed

    def _success_delay(self) -> float:
        return max(
            30.0,
            self.interval_seconds
            + self._jitter(-self.jitter_seconds, self.jitter_seconds),
        )

    def _failure_delay(self, failures: int) -> float:
        base = self.interval_seconds * (2 ** (failures - 1))
        return min(300.0, base + self._jitter(0.0, self.jitter_seconds))

    def _loop(self) -> None:
        failures = 0
        delay = 0.0
        while not self._stop.wait(delay):
            try:
                processed = self.poll_once()
                now = self._now()
                with self._state_lock:
                    self._healthy = True
                    self._last_success = now
                failures = 0
                delay = self._success_delay()
                LOGGER.info("delivery poll succeeded processed=%d", processed)
            except PolicyError as exc:
                failures += 1
                with self._state_lock:
                    self._healthy = False
                delay = self._failure_delay(failures)
                LOGGER.warning("delivery poll failed code=%s retry_seconds=%d", exc.code, delay)
            except Exception:
                failures += 1
                with self._state_lock:
                    self._healthy = False
                delay = self._failure_delay(failures)
                LOGGER.exception("delivery poll failed unexpectedly retry_seconds=%d", delay)


__all__ = ["DeliveryItem", "DeliveryPoller", "PolledDeliveryProcessor"]
