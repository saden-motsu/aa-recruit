from __future__ import annotations

# Standard Library
from itertools import chain

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import (
    CharacterContact,
    CharacterContract,
    CharacterMail,
    CharacterWalletJournalEntry,
)
from memberaudit.models.general import MailEntity

# Django
from django.db.models import F, FloatField, Sum

# Alliance Auth (External Libs)
from eveuniverse.models import EveEntity

from .character_event import CharacterEvent


def get_all_events(character_query_set: CharacterQuerySet) -> list[CharacterEvent]:
    """
    Collect all supported events for the given characters and convert to DTOs.
    """
    contact_events = _get_contact_events(character_query_set)
    mail_events = _get_mail_events(character_query_set)
    character_contract_events = _get_character_contracts(character_query_set)
    wallet_events = _get_wallet_journal_entries(character_query_set)
    return list(
        chain(contact_events, mail_events, character_contract_events, wallet_events)
    )


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
                details=f"{other.name or str(other.id)}: Standings {character_contact.standing}",
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
                    other_character_name=mail_entity.name,
                    details=_get_mail_details(character_mail),
                    timestamp=character_mail.timestamp,
                )
            )

    return result


def _get_mail_details(character_mail: CharacterMail) -> str:
    return f"""{"" if character_mail.is_read else "Unread:"}Subject:{character_mail.subject}
From:{character_mail.sender.name_plus}
To:{",".join(x.name_plus for x in character_mail.recipients.all())}
{character_mail.body_html}
"""


def _get_character_contracts(
    character_query_set: CharacterQuerySet,
) -> list[CharacterEvent]:
    contracts = (
        CharacterContract.objects.filter(character__in=character_query_set)
        .select_related("character", "issuer", "assignee", "acceptor")
        .prefetch_related("items__eve_type")
    )

    character_ids = set(
        character_query_set.values_list("eve_character__character_id", flat=True)
    )

    def _counterparty(contract: CharacterContract) -> EveEntity | None:
        """Pick the most relevant other party for this contract."""
        for entity in (contract.assignee, contract.acceptor, contract.issuer):
            if not entity or not entity.is_character or entity.is_npc:
                continue
            if entity.id in character_ids:
                continue
            return entity
        return None

    def _contract_details(contract: CharacterContract) -> str:
        parts: list[str] = []
        parts.append(
            f"{contract.summary()} ({contract.get_contract_type_display().title()})"
        )

        if title := contract.title:
            parts.append(f"Info by Issuer:{title}")
        if availability := contract.get_availability_display():
            parts.append(
                f"Availability:{availability.capitalize()} - {contract.assignee.name}"
            )
        if issuer := contract.issuer:
            parts.append(f"Contractor:{issuer}")
        parts.append(f"Status:{contract.get_status_display().title()}")

        isk_fields = []
        if price := contract.price:
            isk_fields.append(f"Price:{price}")
        if reward := contract.reward:
            isk_fields.append(f"Reward:{reward}")
        if collateral := contract.collateral:
            isk_fields.append(f"Collateral:{collateral}")
        if buyout := contract.buyout:
            isk_fields.append(f"Buyout:{buyout}")
        if isk_fields:
            parts.append(", ".join(isk_fields))

        for item in contract.items.all():
            parts.append(
                f"{item.quantity}x <a href=https://evetycoon.com/market/{item.eve_type.id}>{item.name_display}</a>"
            )

        return "\n".join(parts)

    def _isk_value(contract: CharacterContract):
        return (
            contract.items.all()
            .exclude(raw_quantity__lt=0)
            .aggregate(
                total=Sum(
                    F("quantity") * F("eve_type__market_price__average_price"),
                    output_field=FloatField(),
                )
            )
            .get("total")
        )

    events: list[CharacterEvent] = []
    for contract in contracts:
        other = _counterparty(contract)
        if not other:
            continue
        events.append(
            CharacterEvent(
                recruit_id=contract.character.id,
                recruit_name=contract.character.name,
                other_character_id=other.id,
                other_character_name=other.name,
                details=_contract_details(contract),
                timestamp=contract.date_completed
                or contract.date_expired
                or contract.date_accepted
                or contract.date_issued,
                isk_value=_isk_value(contract),
            )
        )

    return events


def _get_wallet_journal_entries(
    character_query_set: CharacterQuerySet,
) -> list[CharacterEvent]:

    character_wallet_journal_entries = CharacterWalletJournalEntry.objects.filter(
        character__in=character_query_set
    ).select_related("character", "first_party", "second_party")

    character_ids = set(
        character_query_set.values_list("eve_character__character_id", flat=True)
    )

    def _counterparty(entry: CharacterWalletJournalEntry) -> EveEntity | None:
        for entity in (entry.first_party, entry.second_party):
            if not entity or not entity.is_character or entity.is_npc:
                continue
            if entity.id in character_ids:
                continue
            return entity
        return None

    events: list[CharacterEvent] = []
    for character_wallet_journal_entry in character_wallet_journal_entries:
        other = _counterparty(character_wallet_journal_entry)
        if not other:
            continue

        ref_type_display = character_wallet_journal_entry.ref_type.replace(
            "_", " "
        ).title()
        details = f"{ref_type_display}\n{character_wallet_journal_entry.description}"
        if character_wallet_journal_entry.context_id:
            context_type = character_wallet_journal_entry.get_context_id_type_display()
            details = f"{details}\nContext:{context_type} ({character_wallet_journal_entry.context_id})"
        if character_wallet_journal_entry.reason:
            details = f"{details}\nReason:{character_wallet_journal_entry.reason}"

        events.append(
            CharacterEvent(
                recruit_id=character_wallet_journal_entry.character.id,
                recruit_name=character_wallet_journal_entry.character.name,
                other_character_id=other.id,
                other_character_name=other.name,
                details=details,
                timestamp=character_wallet_journal_entry.date,
                isk_value=character_wallet_journal_entry.amount,
            )
        )

    return events
