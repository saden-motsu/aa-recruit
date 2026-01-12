from __future__ import annotations

# Standard Library
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter

# Alliance Auth (External Libs)
from eveuniverse.models import EveEntity


@dataclass(slots=True, order=True, frozen=True)
class CharacterEvent:
    """
    Represents an interaction involving a recruit and another character. Timestamp
    and ISK value are optional because not every event will carry temporal or
    financial context. Details is a human-readable summary of the event.
    """

    recruit: EveCharacter
    other_entity: EveEntity
    summary: str | None = None
    details: str | None = None
    timestamp: datetime | None = None
    isk_value: Decimal | None = None
