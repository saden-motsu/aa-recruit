from __future__ import annotations

# Standard Library
from itertools import chain

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import CharacterContact
from memberaudit.models.character_sections_2 import CharacterMail
from memberaudit.models.general import MailEntity

# Alliance Auth (External Libs)
from eveuniverse.models import EveEntity

from .character_event import CharacterEvent


def get_all_events(character_query_set: CharacterQuerySet) -> list[CharacterEvent]:
    """
    Collect all supported events for the given characters and convert to DTOs.
    """
    contact_events = _get_contact_events(character_query_set)
    mail_events = _get_mail_events(character_query_set)
    return list(chain(contact_events, mail_events))


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

        result.append(
            CharacterEvent(
                recruit_id=character.id,
                recruit_name=character.name,
                other_character_id=other.id,
                other_character_name=other.name,
                details=f"{other.name or str(other.id)}:{character_contact.standing}",
            )
        )
    return result


def _get_mail_events(character_query_set: CharacterQuerySet) -> list[CharacterEvent]:
    character_mails = (
        CharacterMail.objects.filter(character__in=character_query_set)
        .select_related("sender")
        .prefetch_related("recipients")
    )

    result: list[CharacterEvent] = []
    character_ids = set(
        character_query_set.values_list("eve_character__character_id", flat=True)
    )
    for character_mail in character_mails:
        mail_entities: list[MailEntity] = list(character_mail.recipients.all())
        mail_entities.append(character_mail.sender)
        for mail_entity in mail_entities:
            if mail_entity.id in character_ids:
                continue

            if mail_entity.category == MailEntity.Category.CHARACTER:
                if EveEntity.is_npc_id(mail_entity.id):
                    continue

            result.append(
                CharacterEvent(
                    recruit_id=character_mail.character.id,
                    recruit_name=character_mail.character.name,
                    other_character_id=mail_entity.id,
                    other_character_name=mail_entity.name_plus,
                    details=_get_mail_details(character_mail),
                    timestamp=character_mail.timestamp,
                )
            )

    return result


def _get_mail_details(character_mail: CharacterMail) -> str:
    return f"""{"" if character_mail.is_read else "Unread:"}Subject:{character_mail.subject}
From:{character_mail.sender.name_plus}
To:{",".join(x.name_plus for x in character_mail.recipients.all())}
{character_mail.body}
"""
