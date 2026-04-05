from __future__ import annotations

# Standard Library
import html
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterLocation,
    CharacterMail,
    CharacterMiningLedgerEntry,
    CharacterPlanet,
    CharacterWalletJournalEntry,
    CharacterWalletTransaction,
    Location,
)
from memberaudit.models.general import MailEntity

# Django
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, FloatField, Sum

# Alliance Auth (External Libs)
from eveuniverse.models import EveEntity, EveSolarSystem, EveType

from .interaction import Interaction


@dataclass
class LocationInformation:
    clone_implants: dict[Character, list[EveType]] | None = None
    transactions: list[CharacterWalletTransaction] = field(default_factory=list)
    contracts: set[CharacterContract] = field(default_factory=set)
    assets: list[CharacterAsset] = field(default_factory=list)
    characters_home: set[Character] = field(default_factory=set)


@dataclass
class SystemInformation:
    location_information: dict[Location, LocationInformation] = field(
        default_factory=lambda: defaultdict(LocationInformation)
    )
    mining_ledger_entries: list[CharacterMiningLedgerEntry] = field(
        default_factory=list
    )
    planets: list[CharacterPlanet] = field(default_factory=list)
    characters_in_space: set[Character] = field(default_factory=set)


@dataclass(slots=True)
class RecruitInteractionSnapshot:
    character_ids: set[int]
    characters: list[Character]
    interactions: list[Interaction]
    system_information: dict[EveSolarSystem, SystemInformation]


def collect_recruit_interaction_snapshot(
    characterQuerySet: CharacterQuerySet,
) -> RecruitInteractionSnapshot:

    characters = _load_characters(characterQuerySet)
    character_ids = {
        character.eve_character.character_id
        for character in characters
        if getattr(character, "eve_character", None)
    }
    interactions = [
        *_collect_contact_interactions(characters, character_ids),
        *_collect_mail_interactions(characters, character_ids),
        *_collect_contract_interactions(characters, character_ids),
        *_collect_wallet_journal_interactions(characters, character_ids),
        *_collect_wallet_transaction_interactions(characters, character_ids),
    ]
    system_information = _collect_system_information(characters)
    return RecruitInteractionSnapshot(
        character_ids=character_ids,
        characters=characters,
        interactions=interactions,
        system_information=system_information,
    )


def _load_characters(character_query_set: CharacterQuerySet) -> list[Character]:
    loaded_characters = character_query_set.select_related(
        "eve_character",
        "clone_info__home_location__eve_solar_system",
        "location__eve_solar_system",
    ).prefetch_related(
        "implants__eve_type",
        "jump_clones__location__eve_solar_system",
        "jump_clones__implants__eve_type",
        "contacts__eve_entity",
        "mails__sender",
        "mails__recipients",
        "wallet_transactions__location__eve_solar_system",
        "wallet_transactions__client",
        "wallet_transactions__eve_type__market_price",
        "contracts__start_location__eve_solar_system",
        "contracts__end_location__eve_solar_system",
        "contracts__issuer",
        "contracts__assignee",
        "contracts__acceptor",
        "contracts__items__eve_type",
        "wallet_journal__first_party",
        "wallet_journal__second_party",
        "assets__location__eve_solar_system",
        "assets__eve_type__market_price",
        "mining_ledger__eve_solar_system",
        "planets__eve_planet__eve_solar_system",
        "planets__eve_planet__eve_type",
    )
    return list(loaded_characters)


def _safe_related(instance, attribute_name: str):
    try:
        return getattr(instance, attribute_name)
    except ObjectDoesNotExist:
        return None


def _iter_related(instance, attribute_name: str):
    related_manager = _safe_related(instance, attribute_name)
    if related_manager is None:
        return []
    return related_manager.all()


def _asset_estimated_value(asset: CharacterAsset) -> float:
    average_price = getattr(
        getattr(asset.eve_type, "market_price", None), "average_price", 0
    )
    return float(asset.quantity or 0) * float(average_price or 0)


def _is_external_character_entity(
    entity: EveEntity | None,
    character_ids: set[int],
) -> bool:
    if not entity or not entity.is_character or entity.is_npc:
        return False
    return entity.id not in character_ids


def _is_relevant_mail_entity(mail_entity: MailEntity, character_ids: set[int]) -> bool:
    if mail_entity.id in character_ids:
        return False
    if mail_entity.category == MailEntity.Category.CHARACTER and EveEntity.is_npc_id(
        mail_entity.id
    ):
        return False
    return mail_entity.category in MailEntity.Category.eve_entity_compatible()


def _mail_summary(character_mail: CharacterMail, recipients: list[MailEntity]) -> str:
    sender_name = character_mail.sender.name_plus if character_mail.sender else ""
    recipient_names = ";".join(x.name_plus for x in recipients)
    return f"Mail {sender_name}->{recipient_names}"


def _mail_details(character_mail: CharacterMail, recipients: list[MailEntity]) -> str:
    sender_name = character_mail.sender.name_plus if character_mail.sender else ""
    return f"""{"" if character_mail.is_read else "Unread:"}Subject:{character_mail.subject}
From:{sender_name}
To:{",".join(x.name_plus for x in recipients)}
{character_mail.body_html}
"""


def _contract_counterparty(
    contract: CharacterContract, character_ids: set[int]
) -> EveEntity | None:
    for entity in (contract.assignee, contract.acceptor, contract.issuer):
        if _is_external_character_entity(entity, character_ids):
            return entity
    return None


def _contract_summary(contract: CharacterContract) -> str:
    parts: list[str] = []
    if summary := contract.summary():
        parts.append(str(summary))
    if issuer := contract.issuer:
        parts.append(f"Contractor:{issuer}")
    if availability := contract.get_availability_display():
        assignee_name = contract.assignee.name if contract.assignee else "None"
        parts.append(f"Availability:{availability.capitalize()} - {assignee_name}")
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


def _contract_isk_value(contract: CharacterContract):
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


def _wallet_journal_counterparty(
    entry: CharacterWalletJournalEntry, character_ids: set[int]
) -> EveEntity | None:
    for entity in (entry.first_party, entry.second_party):
        if _is_external_character_entity(entity, character_ids):
            return entity
    return None


def _wallet_transaction_counterparty(
    transaction: CharacterWalletTransaction, character_ids: set[int]
) -> EveEntity | None:
    client = transaction.client
    if _is_external_character_entity(client, character_ids):
        return client
    return None


def _wallet_transaction_ratio(
    transaction: CharacterWalletTransaction,
) -> Decimal | None:
    market_price = _wallet_transaction_average_price(transaction)
    if market_price is None or market_price <= 0:
        return None
    try:
        return Decimal(transaction.unit_price) / Decimal(market_price)
    except (ArithmeticError, ValueError):
        return None


def _wallet_transaction_average_price(
    transaction: CharacterWalletTransaction,
) -> Decimal | float | None:
    try:
        market_price = transaction.eve_type.market_price
    except (AttributeError, ObjectDoesNotExist):
        return None
    return getattr(market_price, "average_price", None)


def _collect_contact_interactions(
    characters: list[Character],
    character_ids: set[int],
) -> list[Interaction]:
    result: list[Interaction] = []
    for character in characters:
        for character_contact in _iter_related(character, "contacts"):
            other = character_contact.eve_entity
            if not _is_external_character_entity(other, character_ids):
                continue
            result.append(
                Interaction(
                    recruit=character_contact.character,
                    other_entity=other,
                    kind="contact",
                    summary=f"Standings {character_contact.standing:+}",
                    timestamp=None,
                )
            )
    return result


def _collect_mail_interactions(
    characters: list[Character],
    character_ids: set[int],
) -> list[Interaction]:
    character_mails = [
        character_mail
        for character in characters
        for character_mail in _iter_related(character, "mails")
    ]
    mail_recipients = {
        character_mail.pk: list(character_mail.recipients.all())
        for character_mail in character_mails
    }
    entity_ids: set[int] = set()
    for character_mail in character_mails:
        entity_ids.update(entity.id for entity in mail_recipients[character_mail.pk])
        if character_mail.sender:
            entity_ids.add(character_mail.sender.id)
    entities_by_id = EveEntity.objects.in_bulk(entity_ids)

    result: list[Interaction] = []
    for character_mail in character_mails:
        recipients = mail_recipients[character_mail.pk]
        summary = _mail_summary(character_mail, recipients)
        details = _mail_details(character_mail, recipients)
        mail_entities = list(recipients)
        if character_mail.sender:
            mail_entities.append(character_mail.sender)
        for mail_entity in mail_entities:
            if not _is_relevant_mail_entity(mail_entity, character_ids):
                continue
            other_entity = entities_by_id.get(mail_entity.id)
            if other_entity is None:
                continue
            result.append(
                Interaction(
                    recruit=character_mail.character,
                    other_entity=other_entity,
                    kind="mail",
                    summary=summary,
                    details=details,
                    timestamp=character_mail.timestamp,
                )
            )
    return result


def _collect_contract_interactions(
    characters: list[Character],
    character_ids: set[int],
) -> list[Interaction]:
    result: list[Interaction] = []
    for character in characters:
        for contract in _iter_related(character, "contracts"):
            other = _contract_counterparty(contract, character_ids)
            if not other:
                continue
            isk_value = _contract_isk_value(contract)
            location = contract.end_location or contract.start_location
            result.append(
                Interaction(
                    recruit=contract.character,
                    other_entity=other,
                    kind="contract",
                    summary=_contract_summary(contract),
                    details=_contract_details(contract, isk_value),
                    timestamp=contract.date_completed
                    or contract.date_expired
                    or contract.date_accepted
                    or contract.date_issued,
                    isk_value=isk_value,
                    location=location,
                )
            )
    return result


def _collect_wallet_journal_interactions(
    characters: list[Character],
    character_ids: set[int],
) -> list[Interaction]:
    result: list[Interaction] = []
    for character in characters:
        for entry in _iter_related(character, "wallet_journal"):
            other = _wallet_journal_counterparty(entry, character_ids)
            if not other:
                continue
            if entry.ref_type not in {"player_donation", "player_trading"}:
                continue

            summary = entry.ref_type.replace("_", " ").title()
            detail_parts: list[str] = []
            if entry.context_id:
                context_type = entry.get_context_id_type_display()
                detail_parts.append(f"Context:{context_type} ({entry.context_id})")
            if entry.reason:
                detail_parts.append(f"Reason:{entry.reason}")

            result.append(
                Interaction(
                    recruit=entry.character,
                    other_entity=other,
                    kind="wallet_journal",
                    summary=summary,
                    details="\n".join(detail_parts) or None,
                    timestamp=entry.date,
                    isk_value=entry.amount,
                )
            )
    return result


def _collect_wallet_transaction_interactions(
    characters: list[Character],
    character_ids: set[int],
) -> list[Interaction]:
    result: list[Interaction] = []
    for character in characters:
        for transaction in _iter_related(character, "wallet_transactions"):
            other = _wallet_transaction_counterparty(transaction, character_ids)
            if not other:
                continue

            ratio = _wallet_transaction_ratio(transaction)
            if ratio is None or (Decimal("0.1") < ratio < Decimal("2")):
                continue

            total_price = transaction.quantity * transaction.unit_price
            if total_price < 10_000_000:
                continue

            average_price = _wallet_transaction_average_price(transaction)
            if average_price is None:
                continue

            side = "Buy" if transaction.is_buy else "Sell"
            percent = float(ratio * Decimal("100"))
            result.append(
                Interaction(
                    recruit=transaction.character,
                    other_entity=other,
                    kind="wallet_transaction",
                    summary=f"{side} {transaction.quantity}x {transaction.eve_type.name}",
                    details=(
                        f"Unit:{transaction.unit_price} Avg:{average_price} "
                        f"({percent:.1f}% of avg)"
                    ),
                    timestamp=transaction.date,
                    isk_value=transaction.unit_price * transaction.quantity,
                    location=transaction.location,
                )
            )
    return result


def _collect_system_information(
    characters: list[Character],
) -> dict[EveSolarSystem, SystemInformation]:
    system_information: dict[EveSolarSystem, SystemInformation] = defaultdict(
        SystemInformation
    )

    def get_location_information(
        location: Location | None,
    ) -> LocationInformation | None:
        if location and location.eve_solar_system:
            return system_information[location.eve_solar_system].location_information[
                location
            ]
        return None

    def get_character_location_information(
        character_location: CharacterLocation | None,
    ) -> tuple[Location | None, LocationInformation | None]:
        if character_location is None:
            return None, None
        location_safe = character_location.location_safe()
        if not location_safe or not location_safe.eve_solar_system:
            return None, None
        info = system_information[location_safe.eve_solar_system].location_information[
            location_safe
        ]
        return location_safe, info

    for character in characters:
        clone_info = _safe_related(character, "clone_info")
        if clone_info and (
            location_information := get_location_information(clone_info.home_location)
        ):
            location_information.characters_home.add(character)

        current_location, location_information = get_character_location_information(
            _safe_related(character, "location")
        )
        if location_information:
            if location_information.clone_implants is None:
                location_information.clone_implants = {}
            location_information.clone_implants[character] = [
                implant.eve_type for implant in _iter_related(character, "implants")
            ]
            if current_location and getattr(current_location, "is_solar_system", False):
                system_information[
                    current_location.eve_solar_system
                ].characters_in_space.add(character)

        for jump_clone in _iter_related(character, "jump_clones"):
            if location_information := get_location_information(jump_clone.location):
                if location_information.clone_implants is None:
                    location_information.clone_implants = {}
                location_information.clone_implants[jump_clone.character] = [
                    implant.eve_type for implant in jump_clone.implants.all()
                ]

        for wallet_transaction in _iter_related(character, "wallet_transactions"):
            location_information = get_location_information(wallet_transaction.location)
            if location_information:
                location_information.transactions.append(wallet_transaction)

        for contract in _iter_related(character, "contracts"):
            if location_information := get_location_information(
                contract.start_location
            ):
                location_information.contracts.add(contract)
            if location_information := get_location_information(contract.end_location):
                location_information.contracts.add(contract)

        for asset in _iter_related(character, "assets"):
            if location_information := get_location_information(asset.location):
                location_information.assets.append(asset)

        for mining_ledger_entry in _iter_related(character, "mining_ledger"):
            if mining_ledger_entry.eve_solar_system:
                system_information[
                    mining_ledger_entry.eve_solar_system
                ].mining_ledger_entries.append(mining_ledger_entry)

        for planet in _iter_related(character, "planets"):
            if planet.eve_planet and planet.eve_planet.eve_solar_system:
                system_information[planet.eve_planet.eve_solar_system].planets.append(
                    planet
                )

    for info in system_information.values():
        for location_info in info.location_information.values():
            location_info.assets.sort(key=_asset_estimated_value, reverse=True)

    return system_information
