from __future__ import annotations

# Standard Library
import html
from dataclasses import dataclass
from decimal import Decimal

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterLocation,
    CharacterMail,
    CharacterWalletJournalEntry,
    CharacterWalletTransaction,
    Location,
)
from memberaudit.models.general import MailEntity

# Django
from django.contrib.humanize.templatetags.humanize import intword
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, FloatField, Sum

# Alliance Auth (External Libs)
from eveuniverse.constants import EveCategoryId
from eveuniverse.models import EveEntity, EveSolarSystem

from .external_character import ExternalEntityProfile, enrich_profiles
from .interaction import Interaction


@dataclass(slots=True)
class RecruitInteractionSnapshot:
    character_ids: set[int]
    characters: list[Character]
    interactions: list[Interaction]


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
        *_collect_location_interactions(characters),
    ]

    unique_entities = _get_unique_external_entities(interactions)
    profiles_by_id = enrich_profiles(unique_entities)
    for interaction in interactions:
        if interaction.external_entity_profile is not None:
            entity_id = interaction.external_entity_profile.entity.id
            interaction.external_entity_profile = profiles_by_id.get(entity_id)

    return RecruitInteractionSnapshot(
        character_ids=character_ids,
        characters=characters,
        interactions=interactions,
    )


def _load_characters(character_query_set: CharacterQuerySet) -> list[Character]:
    loaded_characters = character_query_set.select_related(
        "eve_character",
        "clone_info__home_location__eve_solar_system",
        "clone_info__home_location__owner",
        "location__eve_solar_system",
        "location__location__owner",
    ).prefetch_related(
        "implants__eve_type",
        "jump_clones__location__eve_solar_system",
        "jump_clones__location__owner",
        "jump_clones__implants__eve_type",
        "contacts__eve_entity",
        "mails__sender",
        "mails__recipients",
        "wallet_transactions__location__eve_solar_system",
        "wallet_transactions__location__owner",
        "wallet_transactions__client",
        "wallet_transactions__eve_type__market_price",
        "contracts__start_location__eve_solar_system",
        "contracts__start_location__owner",
        "contracts__end_location__eve_solar_system",
        "contracts__end_location__owner",
        "contracts__issuer",
        "contracts__assignee",
        "contracts__acceptor",
        "contracts__items__eve_type",
        "wallet_journal__first_party",
        "wallet_journal__second_party",
        "assets__location__eve_solar_system",
        "assets__location__owner",
        "assets__parent",
        "assets__eve_type__market_price",
        "assets__eve_type__eve_group",
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


def _get_unique_external_entities(interactions: list[Interaction]) -> list[EveEntity]:
    seen: set[int] = set()
    result: list[EveEntity] = []
    for interaction in interactions:
        profile = interaction.external_entity_profile
        if profile is None or profile.entity.id in seen:
            continue
        seen.add(profile.entity.id)
        result.append(profile.entity)
    return result


def _asset_estimated_value(asset: CharacterAsset) -> float:
    average_price = getattr(
        getattr(asset.eve_type, "market_price", None), "average_price", 0
    )
    return float(asset.quantity or 0) * float(average_price or 0)


def _is_ship_asset(asset: CharacterAsset) -> bool:
    eve_group = getattr(asset.eve_type, "eve_group", None)
    return getattr(eve_group, "eve_category_id", None) == EveCategoryId.SHIP


def _aggregate_asset_values(
    assets: list[CharacterAsset],
) -> tuple[dict[int, float], set[int]]:
    children_by_parent_id: dict[int, list[CharacterAsset]] = {}
    for asset in assets:
        if asset.parent_id:
            children_by_parent_id.setdefault(asset.parent_id, []).append(asset)

    def subtree_value(asset: CharacterAsset) -> float:
        own_value = _asset_estimated_value(asset)
        for child in children_by_parent_id.get(asset.id, []):
            own_value += subtree_value(child)
        return own_value

    aggregated_values: dict[int, float] = {}
    assets_inside_ships: set[int] = set()

    for asset in assets:
        if _is_ship_asset(asset):
            aggregated_values[asset.id] = subtree_value(asset)
            for child in children_by_parent_id.get(asset.id, []):
                stack = [child]
                while stack:
                    descendant = stack.pop()
                    assets_inside_ships.add(descendant.id)
                    stack.extend(children_by_parent_id.get(descendant.id, []))
        else:
            aggregated_values[asset.id] = _asset_estimated_value(asset)

    return aggregated_values, assets_inside_ships


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
        isk_fields.append(f"ISK Value:{intword(isk_value)}")
    if price := contract.price:
        isk_fields.append(f"Price:{intword(price)}")
    if reward := contract.reward:
        isk_fields.append(f"Reward:{intword(reward)}")
    if collateral := contract.collateral:
        isk_fields.append(f"Collateral:{intword(collateral)}")
    if buyout := contract.buyout:
        isk_fields.append(f"Buyout:{intword(buyout)}")
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


def _character_location_safe(
    character_location: CharacterLocation | None,
) -> Location | None:
    if character_location is None:
        return None
    return character_location.location_safe()


def _solar_system_from_location(location: Location | None) -> EveSolarSystem | None:
    if location is None:
        return None
    return getattr(location, "eve_solar_system", None)


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
                    external_entity_profile=ExternalEntityProfile(entity=other),
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
                    external_entity_profile=ExternalEntityProfile(entity=other_entity),
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
                    external_entity_profile=ExternalEntityProfile(entity=other),
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
                    external_entity_profile=ExternalEntityProfile(entity=other),
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
                    external_entity_profile=ExternalEntityProfile(entity=other),
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


def _collect_location_interactions(
    characters: list[Character],
) -> list[Interaction]:
    result: list[Interaction] = []

    for character in characters:
        clone_info = _safe_related(character, "clone_info")
        home_location = getattr(clone_info, "home_location", None)
        if _solar_system_from_location(home_location):
            result.append(
                Interaction(
                    recruit=character,
                    kind="clone_home",
                    summary=f"{character.name} home station",
                    location=home_location,
                )
            )

        current_location = _character_location_safe(
            _safe_related(character, "location")
        )
        implants = [
            implant.eve_type for implant in _iter_related(character, "implants")
        ]
        if _solar_system_from_location(current_location):
            result.append(
                Interaction(
                    recruit=character,
                    kind="clone",
                    summary=character.name,
                    location=current_location,
                    eve_types=implants,
                )
            )
            if getattr(current_location, "is_solar_system", False):
                result.append(
                    Interaction(
                        recruit=character,
                        kind="character_in_space",
                        summary=f"{character.name} in space",
                        solar_system=current_location.eve_solar_system,
                    )
                )

        for jump_clone in _iter_related(character, "jump_clones"):
            if _solar_system_from_location(jump_clone.location):
                result.append(
                    Interaction(
                        recruit=jump_clone.character,
                        kind="jump_clone",
                        summary=jump_clone.character.name,
                        location=jump_clone.location,
                        eve_types=[
                            implant.eve_type for implant in jump_clone.implants.all()
                        ],
                    )
                )

        character_assets = list(_iter_related(character, "assets"))
        asset_values, assets_inside_ships = _aggregate_asset_values(character_assets)
        for asset in character_assets:
            if asset.id in assets_inside_ships:
                continue
            estimated_value = asset_values.get(asset.id, 0)
            location = asset.location
            if not _solar_system_from_location(location):
                continue
            result.append(
                Interaction(
                    recruit=asset.character,
                    kind="asset",
                    summary=asset.name_display,
                    isk_value=estimated_value,
                    location=location,
                )
            )

        for mining_ledger_entry in _iter_related(character, "mining_ledger"):
            if mining_ledger_entry.eve_solar_system:
                result.append(
                    Interaction(
                        recruit=character,
                        kind="mining_ledger",
                        summary=str(mining_ledger_entry),
                        solar_system=mining_ledger_entry.eve_solar_system,
                    )
                )

        for planet in _iter_related(character, "planets"):
            if planet.eve_planet and planet.eve_planet.eve_solar_system:
                result.append(
                    Interaction(
                        recruit=character,
                        kind="planet",
                        summary=(
                            f"{planet.eve_planet.name} "
                            f"({planet.eve_planet.type_name()})"
                        ),
                        solar_system=planet.eve_planet.eve_solar_system,
                    )
                )

    return result
