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
from eveuniverse.models import EveEntity


@dataclass
class Interaction:
    recruit: Character
    other_entity: EveEntity
    kind: str
    timestamp: datetime | None
    summary: str
    details: str | None = None
    isk_value: float | Decimal | None = None
    location: Location | None = None
