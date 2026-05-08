from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from django.core.cache import cache
from eveuniverse.models import EveEntity
from eveuniverse.providers import esi

logger = logging.getLogger(__name__)

_CORP_HISTORY_TTL = 60 * 60 * 24  # 1 day
_MAX_ESI_WORKERS = 5


@dataclass
class CorpHistoryEntry:
    entity: EveEntity
    start_date: datetime

@dataclass
class ExternalEntityProfile:
    entity: EveEntity
    corp_history: list[CorpHistoryEntry] = field(default_factory=list)


def enrich_profiles(entities: Iterable[EveEntity]) -> dict[int, ExternalEntityProfile]:
    profiles = {e.id: ExternalEntityProfile(entity=e) for e in entities}
    profile_list = list(profiles.values())
    _enrich_corp_histories(profile_list)
    _enrich_character_corp_histories(profile_list)
    _enrich_corp_entities(profile_list)
    return profiles


def _enrich_corp_histories(profiles: list[ExternalEntityProfile]) -> None:
    for profile in profiles:
        if profile.entity.is_corporation:
            profile.corp_history = [CorpHistoryEntry(entity=profile.entity, start_date=datetime.min)]


def _enrich_character_corp_histories(profiles: list[ExternalEntityProfile]) -> None:
    character_ids = {p.entity.id for p in profiles if p.entity.is_character}
    if not character_ids:
        return

    histories = _fetch_corp_histories(character_ids)
    for profile in profiles:
        if profile.entity.is_character:
            profile.corp_history = histories.get(profile.entity.id, [])


def _fetch_corp_histories(character_ids: set[int]) -> dict[int, list[CorpHistoryEntry]]:
    cached: dict[int, list] = {}
    missing: set[int] = set()
    for character_id in character_ids:
        data = cache.get(f"external_corp_history:{character_id}")
        if data is not None:
            cached[character_id] = data
        else:
            missing.add(character_id)

    if missing:
        missing_list = list(missing)
        with ThreadPoolExecutor(max_workers=_MAX_ESI_WORKERS) as executor:
            for character_id, history in zip(missing_list, executor.map(_fetch_corp_history_esi, missing_list)):
                cached[character_id] = history

    return {
        entity_id: [
            CorpHistoryEntry(
                entity=EveEntity(id=entry["corporation_id"]),
                start_date=entry["start_date"],
            )
            for entry in raw_history
        ]
        for entity_id, raw_history in cached.items()
    }


def _fetch_corp_history_esi(character_id: int) -> list[dict]:
    try:
        history = esi.client.Character.get_characters_character_id_corporationhistory(
            character_id=character_id
        ).results()
        data = [
            {"corporation_id": e["corporation_id"], "start_date": e["start_date"]}
            for e in history
        ]
    except Exception:
        logger.exception("Failed to fetch corp history for character %s", character_id)
        data = []
    cache.set(f"external_corp_history:{character_id}", data, _CORP_HISTORY_TTL)
    return data


def _enrich_corp_entities(profiles: list[ExternalEntityProfile]) -> None:
    corp_ids = set()
    for profile in profiles:
        for entry in profile.corp_history:
            corp_ids.add(entry.entity.id)

    EveEntity.objects.bulk_resolve_ids(corp_ids)
    entities_by_id = EveEntity.objects.in_bulk(list(corp_ids))

    for profile in profiles:
        for entry in profile.corp_history:
            entry.entity = entities_by_id.get(entry.entity.id, entry.entity)