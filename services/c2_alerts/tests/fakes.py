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
