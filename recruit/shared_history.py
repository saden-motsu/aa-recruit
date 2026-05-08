from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from eveuniverse.models import EveEntity

from .corp_alliance_history import AllianceHistoryEntry
from .corp_history import CorpHistoryEntry, EveEntityCorpHistory

_ONGOING = datetime.max.replace(tzinfo=timezone.utc)

_Interval = tuple[EveEntity, datetime, datetime]


@dataclass
class CorpHistoryRow:
    corp: EveEntity
    alliance: EveEntity | None
    start: datetime

EntityHistory = list[CorpHistoryRow]

def get_entity_history(
    entity_profile: EveEntityCorpHistory,
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
) -> EntityHistory:
    result: EntityHistory = []
    for corp_entity, corp_start, corp_end in _corp_intervals(entity_profile.corp_history):
        alliance_history = corp_alliance_histories.get(corp_entity.id, [])
        if not alliance_history:
            result.append(CorpHistoryRow(corp=corp_entity, alliance=None, start=corp_start))
            continue
        for i, entry in enumerate(alliance_history):
            a_end = alliance_history[i - 1].start_date if i > 0 else _ONGOING
            start = max(corp_start, entry.start_date)
            end = min(corp_end, a_end)
            if start < end:
                result.append(CorpHistoryRow(corp=corp_entity, alliance=entry.entity, start=start))
    return result


def _corp_intervals(corp_history: list[CorpHistoryEntry]) -> list[_Interval]:
    result = []
    for i, entry in enumerate(corp_history):
        end = corp_history[i - 1].start_date if i > 0 else _ONGOING
        result.append((entry.entity, entry.start_date, end))
    return result
