from __future__ import annotations

import math

from .app_settings import RECRUIT_ALLY_ALLIANCE_IDS, RECRUIT_ENEMY_ALLIANCE_IDS
from .corp_alliance_history import AllianceHistoryEntry
from .corp_history import EveEntityCorpHistory
from .interaction import Interaction


def count_factor(n: int) -> float:
    return 1 - 2 ** (-0.1 * n)


def score_event_group(events: list) -> float:
    max_score = max((e.priority_score for e in events), default=0.0)
    return min(1.0, max_score + 0.2 * count_factor(len(events)))


_KIND_SCORES: dict[str, float] = {
    "wallet_journal_donation": 0.9,
    "contract_item_exchange": 0.5,
    "wallet_journal_trading": 0.4,
    "contract_courier": 0.3,
    "wallet_transaction": 0.3,
    "mail": 0.2,
    "contact": 0.1,
}


def score_all_interactions(
    interactions: list[Interaction],
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
    recruit_corp_ids: set[int],
    recruit_alliance_ids: set[int],
) -> None:
    for interaction in interactions:
        interaction.priority_score = _score_interaction(
            interaction,
            corp_histories,
            corp_alliance_histories,
            recruit_corp_ids,
            recruit_alliance_ids,
        )


def _score_interaction(
    interaction: Interaction,
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
    recruit_corp_ids: set[int],
    recruit_alliance_ids: set[int],
) -> float:
    if interaction.other_entity is not None:
        return _score_character_interaction(
            interaction,
            corp_histories,
            corp_alliance_histories,
            recruit_corp_ids,
            recruit_alliance_ids,
        )
    return _score_location_interaction(interaction)


def _score_character_interaction(
    interaction: Interaction,
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
    recruit_corp_ids: set[int],
    recruit_alliance_ids: set[int],
) -> float:
    relationship = _relationship_factor(
        interaction,
        corp_histories,
        corp_alliance_histories,
        recruit_corp_ids,
        recruit_alliance_ids,
    )
    kind = _kind_factor(interaction)
    mismatch = _mismatch_factor(interaction.price_ratio)
    isk = _isk_factor(interaction)
    return 0.5 * relationship + 0.3 * kind + 0.15 * mismatch + 0.05 * isk


def _score_location_interaction(interaction: Interaction) -> float:
    system = interaction.solar_system
    if system is None and interaction.location is not None:
        system = getattr(interaction.location, "eve_solar_system", None)
    if system is None:
        return 0.0
    sec = float(system.security_status or 0.0)
    if sec < 0.0:
        return 0.7
    if sec < 0.5:
        return 0.4
    return 0.1


def _get_entity_alliance_id(
    entity_id: int,
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
) -> int | None:
    profile = corp_histories.get(entity_id)
    if not profile or not profile.corp_history:
        return None
    current_corp = profile.corp_history[0].entity
    alliance_entries = corp_alliance_histories.get(current_corp.id, [])
    if not alliance_entries:
        return None
    return alliance_entries[0].entity.id if alliance_entries[0].entity else None


def _relationship_factor(
    interaction: Interaction,
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
    recruit_corp_ids: set[int],
    recruit_alliance_ids: set[int],
) -> float:
    entity = interaction.other_entity
    if entity is None:
        return 0.0

    profile = corp_histories.get(entity.id)
    current_corp = (
        profile.corp_history[0].entity
        if profile and profile.corp_history
        else None
    )
    if current_corp and current_corp.id in recruit_corp_ids:
        return 0.0

    alliance_id = _get_entity_alliance_id(
        entity.id, corp_histories, corp_alliance_histories
    )

    if alliance_id in RECRUIT_ALLY_ALLIANCE_IDS:
        return 0.0
    if alliance_id and alliance_id in recruit_alliance_ids:
        return 0.1
    if alliance_id in RECRUIT_ENEMY_ALLIANCE_IDS:
        return 0.9
    if current_corp or alliance_id:
        return 0.5
    return 0.4  # No affiliation data


def _kind_factor(interaction: Interaction) -> float:
    base = _KIND_SCORES.get(interaction.kind, 0.0)
    if interaction.kind == "contact" and interaction.standing is not None:
        # Bump the kind score for significant positive standings regardless of
        # affiliation; the relationship factor handles the enemy/ally dimension.
        if interaction.standing > 0:
            base = min(1.0, base + interaction.standing / 20.0)
    return base


def _mismatch_factor(price_ratio: float | None) -> float:
    if price_ratio is None:
        return 0.0
    if price_ratio <= 0:
        return 1.0  # free — limit of the curve as ratio → 0
    return 1 - 2 ** (-1.2 * abs(math.log(price_ratio)))


def _isk_factor(interaction: Interaction) -> float:
    if interaction.isk_value is None:
        return 0.0
    total = abs(float(interaction.isk_value))
    if total == 0:
        return 0.0
    if total > 1_000_000_000:
        return 0.9
    if total > 100_000_000:
        return 0.6
    if total > 10_000_000:
        return 0.3
    return 0.1
