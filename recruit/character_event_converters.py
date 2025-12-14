from __future__ import annotations

# Standard Library
from itertools import chain

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import CharacterContact

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter

from .character_event import CharacterEvent


def get_all_events(character_query_set: CharacterQuerySet) -> list[CharacterEvent]:
    """
    Collect all supported events for the given characters and convert to DTOs.
    """
    contact_events = _get_contact_events(character_query_set)
    return list(chain(contact_events))


def _get_contact_events(character_query_set: CharacterQuerySet) -> list[CharacterEvent]:
    character_contacts = (
        CharacterContact.objects.filter(character__in=character_query_set)
        .exclude(eve_entity__id__in=character_query_set)
        .select_related("character", "eve_entity")
    )

    result: list[CharacterEvent] = []
    for character_contact in character_contacts:
        character = character_contact.character
        other = character_contact.eve_entity
        if not other.is_character:
            continue
        if other.is_npc:
            continue

        other_character = EveCharacter.objects.get_character_by_id(other.id)
        other_name = other_character.character_name if other_character else None
        result.append(
            CharacterEvent(
                recruit_id=character.id,
                recruit_name=character.name,
                other_character_id=other.id,
                other_character_name=other_name,
                details=f"Contact with {other_name or str(other.id)} (standing {character_contact.standing})",
            )
        )
    return result
