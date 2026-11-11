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

    def contact_houses(self) -> list[str]:
        self._check()
        return sorted(h for h, contacts in self._contacts.items() if contacts)


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
    """Records what would be sent; can leave contacts unconfirmed or make SNS fail.

    Keeps topics and email subscriptions like SNS does; a pending subscription has no ARN
    (as on AWS), so it cannot be unsubscribed.
    """

    def __init__(self) -> None:
        from app.gateways.notifier import NotifierError, Subscription, TopicSubscription

        self._error = NotifierError
        self._subscription = Subscription
        self._topic_subscription = TopicSubscription
        self.pending: set[str] = set()  # emails whose subscription is not confirmed yet
        self.fail_publish: set[str] = set()  # contact ids whose publish raises
        self.fail_topic = False
        self.fail_houses: set[str] = set()  # houses whose topic calls raise
        self.published: list[dict] = []
        self.topics: dict[str, str] = {}  # house_id -> topic
        self.subscribed: dict[str, dict[str, str | None]] = {}  # topic -> {email: arn}
        self.unsubscribed: list[str] = []

    def ensure_topic(self, house_id: str) -> str:
        if self.fail_topic or house_id in self.fail_houses:
            raise self._error("sns create_topic failed: Throttling")
        topic = f"arn:aws:sns:us-west-2:000000000000:homeai-house-{house_id}"
        self.topics[house_id] = topic
        return topic

    def ensure_subscription(self, topic: str, email: str, contact_id: str):
        confirmed = email not in self.pending
        subs = self.subscribed.setdefault(topic, {})
        arn = f"{topic}:{contact_id}"
        if email.lower() not in subs:  # new address: drop this contact's confirmed old one
            for old, old_arn in list(subs.items()):
                if old_arn == arn:
                    del subs[old]
                    self.unsubscribed.append(old_arn)
        subs[email.lower()] = arn if confirmed else None
        return self._subscription(contact_id, email, confirmed=confirmed)

    def house_topics(self) -> dict[str, str]:
        return dict(self.topics)

    def email_subscriptions(self, topic: str):
        return [self._topic_subscription(e, a) for e, a in self.subscribed.get(topic, {}).items()]

    def unsubscribe(self, arn: str) -> None:
        for subs in self.subscribed.values():
            for email, sub_arn in list(subs.items()):
                if sub_arn == arn:
                    del subs[email]
        self.unsubscribed.append(arn)

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


class FakeClipReader:
    """C1 playback URLs by media_id; records the lookups (``None`` for an unknown clip)."""

    def __init__(self, urls: dict[str, str] | None = None):
        self.urls = dict(urls or {})
        self.calls: list[str] = []

    def playback_url(self, media_id: str) -> str | None:
        self.calls.append(media_id)
        return self.urls.get(media_id)
