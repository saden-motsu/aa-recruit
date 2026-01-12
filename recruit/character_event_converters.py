from __future__ import annotations

# Standard Library
import html
from decimal import Decimal
from itertools import chain

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import (
    CharacterContact,
    CharacterContract,
    CharacterMail,
    CharacterWalletJournalEntry,
    CharacterWalletTransaction,
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
    wallet_transaction_events = _get_wallet_transactions(character_query_set)
    return list(
        chain(
            contact_events,
            mail_events,
            character_contract_events,
            wallet_events,
            wallet_transaction_events,
        )
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
                recruit=character,
                other_entity=other,
                summary=f"Standings {character_contact.standing:+}",
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
        summary = f"Mail {character_mail.sender.name}->{";".join(x.name_plus for x in character_mail.recipients.all())}"
        for mail_entity in mail_entities:
            if mail_entity.id in character_ids:
                continue

            if mail_entity.category == MailEntity.Category.CHARACTER:
                if EveEntity.is_npc_id(mail_entity.id):
                    continue

            result.append(
                CharacterEvent(
                    recruit=character_mail.character,
                    other_entity=EveEntity.objects.get(pk=mail_entity.id),
                    summary=summary,
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

    def _contract_summary(contract: CharacterContract) -> str:
        parts: list[str] = []
        if summary := contract.summary():
            parts.append(str(summary))

        if issuer := contract.issuer:
            parts.append(f"Contractor:{issuer}")

        if availability := contract.get_availability_display():
            parts.append(
                f"Availability:{availability.capitalize()} - {contract.assignee.name}"
            )

        return "|".join(parts)

    def _contract_details(contract: CharacterContract, isk_value) -> str:
        parts: list[str] = []

        if title := contract.title:
            parts.append(f"Info by Issuer:{html.escape(title)}")
        parts.append(f"Status:{contract.get_status_display().title()}")

        isk_fields = []
        if isk_value:
            isk_fields.append(f"ISK Value:{str(isk_value)}")
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
        isk_value = _isk_value(contract)
        events.append(
            CharacterEvent(
                recruit=contract.character,
                other_entity=other,
                summary=_contract_summary(contract),
                details=_contract_details(contract, isk_value),
                timestamp=contract.date_completed
                or contract.date_expired
                or contract.date_accepted
                or contract.date_issued,
                isk_value=isk_value,
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

        ref_type = character_wallet_journal_entry.ref_type
        if ref_type != "player_donation":
            continue

        ref_type_display = character_wallet_journal_entry.ref_type.replace(
            "_", " "
        ).title()
        summary = f"{ref_type_display}"
        details = ""
        if character_wallet_journal_entry.context_id:
            context_type = character_wallet_journal_entry.get_context_id_type_display()
            details += f"{details}\nContext:{context_type} ({character_wallet_journal_entry.context_id})"
        if character_wallet_journal_entry.reason:
            details += f"{details}\nReason:{character_wallet_journal_entry.reason}"
        if not details:
            details = None

        events.append(
            CharacterEvent(
                recruit=character_wallet_journal_entry.character,
                other_entity=other,
                summary=summary,
                details=details,
                timestamp=character_wallet_journal_entry.date,
                isk_value=character_wallet_journal_entry.amount,
            )
        )

    return events


def _get_wallet_transactions(
    character_query_set: CharacterQuerySet,
) -> list[CharacterEvent]:
    character_wallet_transactions = CharacterWalletTransaction.objects.filter(
        character__in=character_query_set
    ).select_related("character", "client", "eve_type__market_price")

    character_ids = set(
        character_query_set.values_list("eve_character__character_id", flat=True)
    )

    def _counterparty(tx: CharacterWalletTransaction) -> EveEntity | None:
        client = tx.client
        if not client or not client.is_character or client.is_npc:
            return None
        if client.id in character_ids:
            return None
        return client

    def _ratio(tx: CharacterWalletTransaction) -> Decimal | None:
        market_price = tx.eve_type.market_price.average_price
        if market_price is None or market_price <= 0:
            return None
        try:
            return Decimal(tx.unit_price) / Decimal(market_price)
        except (ArithmeticError, ValueError):
            return None

    events: list[CharacterEvent] = []
    for transaction in character_wallet_transactions:
        other = _counterparty(transaction)
        if not other:
            continue

        ratio = _ratio(transaction)
        if ratio is None or (Decimal("0.1") < ratio < Decimal("2")):
            continue

        total_price = transaction.quantity * transaction.unit_price
        if total_price < 10_000_000:
            continue

        side = "Buy" if transaction.is_buy else "Sell"
        percent = float(ratio * Decimal("100"))
        summary = f"{side} {transaction.quantity}x {transaction.eve_type.name}"
        details = (
            f"Unit:{transaction.unit_price} Avg:{transaction.eve_type.market_price.average_price} "
            f"({percent:.1f}% of avg)"
        )

        events.append(
            CharacterEvent(
                recruit=transaction.character,
                other_entity=other,
                summary=summary,
                details=details,
                timestamp=transaction.date,
                isk_value=transaction.unit_price * transaction.quantity,
            )
        )

    return events
