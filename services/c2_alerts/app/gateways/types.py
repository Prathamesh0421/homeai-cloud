"""What C2 reads from other components, and the reader interfaces its services depend on.

Sources (all read-only, docs/02_CONTRACTS.md §4.2 and §4.5):
* C4 ``c4.house_service_settings``, ``c4.emergency_contacts`` (role ``c2_reader``)
* C1 ``c1.houses``, ``c1.rooms`` (role ``c2_reader``)
* C3 Mongo ``ai_detections`` (user ``c2_reader``)

Services take these Protocols so tests can pass the fakes in ``tests/fakes.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.constants import SERVICE_CODES


class DependencyUnavailableError(Exception):
    """A source C2 reads from is down or not deployed yet; the API answers 503."""

    def __init__(self, source: str, detail: str = ""):
        self.source = source
        super().__init__(f"{source} unavailable{': ' + detail if detail else ''}")


class InvalidDetectionError(Exception):
    """An ``ai_detections`` document does not match contract §4.2."""


# --- C1 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class House:
    house_id: str
    tenant_id: str
    name: str
    timezone: str  # IANA, e.g. America/Los_Angeles


@dataclass(frozen=True)
class Room:
    room_id: str
    house_id: str
    name: str


# --- C4 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HouseSettings:
    house_id: str
    tenant_id: str | None
    enabled_services: frozenset[str]
    quiet_start: time | None  # house-local; both or neither
    quiet_end: time | None
    sensitivity: str  # low | medium | high
    is_default: bool = False

    @classmethod
    def defaults(cls, house_id: str, tenant_id: str | None = None) -> HouseSettings:
        """No settings row: all services on, no quiet hours, medium (contracts §4.5)."""
        return cls(
            house_id=house_id,
            tenant_id=tenant_id,
            enabled_services=frozenset(SERVICE_CODES),
            quiet_start=None,
            quiet_end=None,
            sensitivity="medium",
            is_default=True,
        )

    @property
    def has_quiet_hours(self) -> bool:
        return self.quiet_start is not None and self.quiet_end is not None


@dataclass(frozen=True)
class Contact:
    contact_id: str
    name: str
    email: str
    contact_type: str
    priority: int


# --- C3 -------------------------------------------------------------------------------------


class DetectionLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    confidence: float
    source_class: str | None = None
    start_s: float | None = None
    end_s: float | None = None


class DetectionModelRef(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    model_id: str
    name: str
    version: str


class Detection(BaseModel):
    """``ai_detections`` document (contract §4.2). ``top_label`` is ``"none"`` when nothing matched."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, protected_namespaces=())

    detection_id: str = Field(alias="_id")
    media_id: str
    tenant_id: str
    house_id: str
    room_id: str | None = None
    model: DetectionModelRef | None = None
    labels: list[DetectionLabel] = Field(default_factory=list)
    top_label: str
    top_confidence: float
    detected_at: datetime


# --- reader interfaces ----------------------------------------------------------------------


class SettingsReader(Protocol):
    def settings(self, house_id: str) -> HouseSettings: ...

    def contacts(self, house_id: str) -> list[Contact]: ...


class HouseReader(Protocol):
    def house(self, house_id: str) -> House | None: ...

    def room(self, room_id: str) -> Room | None: ...

    def houses(self, house_ids: Iterable[str]) -> dict[str, House]: ...

    def rooms(self, room_ids: Iterable[str]) -> dict[str, Room]: ...


class DetectionReader(Protocol):
    def get(self, detection_id: str) -> Detection | None: ...
