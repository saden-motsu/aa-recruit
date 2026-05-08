from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from eveuniverse.models import EveEntity
from eveuniverse.providers import esi

logger = logging.getLogger(__name__)

_ALLIANCE_HISTORY_TTL = 60 * 60 * 24  # 1 day
_MAX_ESI_WORKERS = 5


@dataclass
class AllianceHistoryEntry:
    entity: EveEntity | None
    start_date: datetime


def get_corp_alliance_histories(
    corp_ids: set[int],
) -> dict[int, list[AllianceHistoryEntry]]:
    alliance_histories = _fetch_alliance_histories(corp_ids)
    alliance_entities = _resolve_alliance_ids(alliance_histories)
    return _convert_to_alliance_history_entries(alliance_histories, alliance_entities)


def _fetch_alliance_histories(corp_ids: set[int]) -> dict[int, list[dict]]:
    cached, missing = {}, set()
    for corp_id in corp_ids:
        data = cache.get(f"ext_alliance_history:{corp_id}")
        if data is not None:
            cached[corp_id] = data
        else:
            missing.add(corp_id)

    if missing:
        missing_list = list(missing)
        with ThreadPoolExecutor(max_workers=_MAX_ESI_WORKERS) as executor:
            for corp_id, history in zip(missing_list, executor.map(_fetch_alliance_history_esi, missing_list)):
                cached[corp_id] = history

    return cached

def _resolve_alliance_ids(
    alliance_histories: dict[int, list[dict]],
) -> dict[int, EveEntity]:
    alliance_ids: set[int] = set()
    for history in alliance_histories.values():
        for entry in history:
            if entry["alliance_id"] is not None:
                alliance_ids.add(entry["alliance_id"])
    EveEntity.objects.bulk_resolve_ids(alliance_ids)
    return EveEntity.objects.in_bulk(list(alliance_ids))


def _fetch_alliance_history_esi(corporation_id: int) -> list[dict]:
    try:
        history = esi.client.Corporation.get_corporations_corporation_id_alliancehistory(
            corporation_id=corporation_id
        ).results()
        data = [
            {"alliance_id": e.get("alliance_id"), "start_date": e["start_date"]}
            for e in history
        ]
    except Exception:
        logger.exception("Failed to fetch alliance history for corp %s", corporation_id)
        data = []
    cache.set(f"ext_alliance_history:{corporation_id}", data, _ALLIANCE_HISTORY_TTL)
    return data


def _convert_to_alliance_history_entries(
    alliance_histories: dict[int, list[dict]],
    alliance_entities: dict[int, EveEntity],
) -> dict[int, list[AllianceHistoryEntry]]:
    result: dict[int, list[AllianceHistoryEntry]] = {}
    for corp_id, history in alliance_histories.items():
        entries = []
        for entry in history:
            alliance_id = entry["alliance_id"]
            entity = alliance_entities.get(alliance_id) if alliance_id is not None else None
            entries.append(AllianceHistoryEntry(
                entity=entity,
                start_date=entry["start_date"],
            ))
        result[corp_id] = entries
    return result