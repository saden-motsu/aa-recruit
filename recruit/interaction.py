from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from attr import dataclass
from memberaudit.models import Character, Location
from eveuniverse.models import EveSolarSystem, EveType

from .external_character import ExternalEntityProfile


@dataclass
class Interaction:
    recruit: Character
    kind: str
    summary: str
    external_entity_profile: ExternalEntityProfile | None = None
    timestamp: datetime | None = None
    details: str | None = None
    isk_value: float | Decimal | None = None
    location: Location | None = None
    solar_system: EveSolarSystem | None = None
    eve_types: list[EveType] | None = None
