"""In-memory readers with the same behaviour as the real gateways (checked in tests/db and
tests/mongo by running one set of tests against both)."""

from __future__ import annotations

from collections.abc import Iterable

from app.gateways.types import (
    Contact,
    DependencyUnavailableError,
    Detection,
    House,
    HouseSettings,
    Room,
)


class FakeSettingsReader:
    def __init__(
        self,
        settings: Iterable[HouseSettings] = (),
        contacts: dict[str, list[Contact]] | None = None,
    ):
        self._settings = {s.house_id: s for s in settings}
        self._contacts = contacts or {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise DependencyUnavailableError("c4")

    def settings(self, house_id: str) -> HouseSettings:
        self._check()
        return self._settings.get(house_id) or HouseSettings.defaults(house_id)

    def contacts(self, house_id: str) -> list[Contact]:
        self._check()
        return sorted(self._contacts.get(house_id, []), key=lambda c: c.priority)


class FakeHouseReader:
    def __init__(self, houses: Iterable[House] = (), rooms: Iterable[Room] = ()):
        self._houses = {h.house_id: h for h in houses}
        self._rooms = {r.room_id: r for r in rooms}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise DependencyUnavailableError("c1")

    def house(self, house_id: str) -> House | None:
        self._check()
        return self._houses.get(house_id)

    def room(self, room_id: str) -> Room | None:
        self._check()
        return self._rooms.get(room_id)

    def houses(self, house_ids: Iterable[str]) -> dict[str, House]:
        self._check()
        return {i: self._houses[i] for i in set(house_ids) if i in self._houses}

    def rooms(self, room_ids: Iterable[str]) -> dict[str, Room]:
        self._check()
        return {i: self._rooms[i] for i in set(room_ids) if i and i in self._rooms}


class FakeDetectionReader:
    def __init__(self, detections: Iterable[Detection] = ()):
        self._detections = {d.detection_id: d for d in detections}
        self.down = False

    def add(self, detection: Detection) -> None:
        self._detections[detection.detection_id] = detection

    def get(self, detection_id: str) -> Detection | None:
        if self.down:
            raise DependencyUnavailableError("c3")
        return self._detections.get(detection_id)


class FakeNotifier:
    """Records what would be sent; can leave contacts unconfirmed or make SNS fail."""

    def __init__(self) -> None:
        from app.gateways.notifier import NotifierError, Subscription

        self._error = NotifierError
        self._subscription = Subscription
        self.pending: set[str] = set()  # emails whose subscription is not confirmed yet
        self.fail_publish: set[str] = set()  # contact ids whose publish raises
        self.fail_topic = False
        self.published: list[dict] = []

    def ensure_topic(self, house_id: str) -> str:
        if self.fail_topic:
            raise self._error("sns create_topic failed: Throttling")
        return f"arn:aws:sns:us-west-2:000000000000:homeai-house-{house_id}"

    def ensure_subscription(self, topic: str, email: str, contact_id: str):
        return self._subscription(contact_id, email, confirmed=email not in self.pending)

    def publish(self, topic, message, *, contact_id, alert_id, severity) -> str:
        if contact_id in self.fail_publish:
            raise self._error("sns publish failed: InternalError")
        self.published.append(
            {
                "topic": topic,
                "contact_id": contact_id,
                "alert_id": alert_id,
                "severity": severity,
                "message": message,
            }
        )
        return f"msg-{len(self.published)}"
