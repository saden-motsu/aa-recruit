from __future__ import annotations

from .character_event import CharacterEvent
from .interaction import Interaction
from .interaction_collector import RecruitInteractionSnapshot


def get_all_events(
    snapshot: RecruitInteractionSnapshot,
) -> list[CharacterEvent]:
    """
    Collect all supported events for the given characters and convert to DTOs.
    """
    return [
        _interaction_to_character_event(x)
        for x in snapshot.interactions
        if x.other_entity is not None
    ]


def _interaction_to_character_event(interaction: Interaction) -> CharacterEvent:
    assert interaction.other_entity is not None
    return CharacterEvent(
        recruit=interaction.recruit,
        other_entity=interaction.other_entity,
        summary=interaction.summary,
        details=interaction.details,
        timestamp=interaction.timestamp,
        isk_value=interaction.isk_value,
    )
