from __future__ import annotations

# Standard Library
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, order=True, frozen=True)
class CharacterEvent:
    """
    Represents an interaction involving a recruit and another character. Timestamp
    and ISK value are optional because not every event will carry temporal or
    financial context. Details is a human-readable summary of the event.
    """

    recruit_id: int
    recruit_name: str
    other_character_id: int
    other_character_name: str
    details: str = ""
    timestamp: datetime | None = None
    isk_value: Decimal | None = None
