# Standard Library
from datetime import datetime
from decimal import Decimal

# Third Party
from attr import dataclass
from memberaudit.models import (
    Character,
    Location,
)

# Alliance Auth (External Libs)
from eveuniverse.models import EveEntity, EveSolarSystem, EveType


@dataclass
class Interaction:
    recruit: Character
    kind: str
    summary: str
    other_entity: EveEntity | None = None
    timestamp: datetime | None = None
    details: str | None = None
    isk_value: float | Decimal | None = None
    location: Location | None = None
    solar_system: EveSolarSystem | None = None
    eve_types: list[EveType] | None = None
