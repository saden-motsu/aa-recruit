"""App Views"""

# Standard Library
import logging
from collections import defaultdict
from collections.abc import Iterable

from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import Character, CharacterAsset

# Django
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import F, FloatField, Sum
from django.http import HttpResponse
from django.shortcuts import render

# Alliance Auth
from allianceauth.authentication.models import UserProfile

# Alliance Auth (External Libs)
from eveuniverse.models import EveConstellation, EveRegion, EveSolarSystem

from .character_event import CharacterEvent
from .character_event_converters import get_all_events
from .priority import score_all_interactions, score_event_group
from .corp_alliance_history import AllianceHistoryEntry, get_corp_alliance_histories
from .corp_history import EveEntityCorpHistory
from .interaction_collector import (
    RecruitInteractionSnapshot,
    collect_recruit_interaction_snapshot,
)
from .location_converters import get_system_interaction_information
from .shared_history import get_entity_history


def _get_main_characters() -> list[str, str, str]:
    """
    Gets a list of all main character names.
    """

    return (
        UserProfile.objects.exclude(main_character__isnull=True)
        .order_by("-user__date_joined")
        .values_list("user__username", "main_character__character_name", "state__name")
    )


def _get_user_characters(selected_username: str) -> CharacterQuerySet:
    return Character.objects.filter(
        eve_character__character_ownership__user__username=selected_username
    ).order_by("-skillpoints__total")


def _map_character_attributes(
    character_query: CharacterQuerySet,
) -> Iterable[dict[str, Any]]:
    keymap: dict[str, str] = {
        "eve_character__character_id": "id",
        "eve_character__character_name": "name",
        "eve_character__corporation_id": "corporation_id",
        "eve_character__corporation_name": "corporation_name",
        "eve_character__alliance_id": "alliance_id",
        "eve_character__alliance_name": "alliance_name",
        "wallet_balance__total": "wallet_isk",
        "skillpoints__total": "total_sp",
    }
    values_query_set = character_query.values(*keymap.keys())
    for character_values in values_query_set:
        yield_result = {keymap.get(k, k): v for k, v in character_values.items()}
        character_id = yield_result["id"]
        yield_result["asset_value"] = _asset_total_for_character_id(character_id)
        yield yield_result


def _asset_total_for_character_id(character_id: int) -> float:
    return (
        CharacterAsset.objects.filter(
            character__eve_character__character_id=character_id
        )
        .exclude(is_blueprint_copy=True)
        .aggregate(
            total=Sum(
                F("quantity") * F("eve_type__market_price__average_price"),
                output_field=FloatField(),
            )
        )
        .get("total")
    )


def _get_character_names(character_query: CharacterQuerySet) -> Iterable[str]:
    return [
        quote(x)
        for x in character_query.values_list("eve_character__character_name", flat=True)
    ]


def _get_blacklist_url(character_names: Iterable[str]) -> str | None:
    if not character_names:
        return None
    sanitized_names = ",".join(character_names)

    return f"https://gice.goonfleet.com/Blacklist?q={sanitized_names}"


def _get_eve411_url(character_names: Iterable[str]) -> str | None:
    if not character_names:
        return None
    sanitized_names = "%0A".join(character_names)

    return f"https://www.eve411.com/local?pilots={sanitized_names}"


GroupedCharacterEvents = list[tuple[dict, list[CharacterEvent]]]


def _get_recruit_affiliation_ids(
    character_query: CharacterQuerySet,
) -> tuple[set[int], set[int]]:
    corp_ids: set[int] = set()
    alliance_ids: set[int] = set()
    for row in character_query.values(
        "eve_character__corporation_id", "eve_character__alliance_id"
    ):
        if corp_id := row.get("eve_character__corporation_id"):
            corp_ids.add(corp_id)
        if alliance_id := row.get("eve_character__alliance_id"):
            alliance_ids.add(alliance_id)
    return corp_ids, alliance_ids


def _group_character_events(
    character_events: Iterable[CharacterEvent],
    character_ids: set[int],
    corp_histories: dict[int, EveEntityCorpHistory],
    corp_alliance_histories: dict[int, list[AllianceHistoryEntry]],
) -> GroupedCharacterEvents:
    grouped_events: dict[int, list[CharacterEvent]] = defaultdict(list)
    for character_event in character_events:
        grouped_events[character_event.other_entity.id].append(character_event)
    results: GroupedCharacterEvents = []
    for entity_id, events in grouped_events.items():
        if entity_id in character_ids:
            continue

        events.sort(key=lambda x: x.priority_score, reverse=True)

        corp_history = corp_histories.get(entity_id)
        current_corp = corp_history.corp_history[0].entity if corp_history and corp_history.corp_history else None
        alliance_history = corp_alliance_histories.get(current_corp.id, []) if current_corp else []
        current_alliance = alliance_history[0] if alliance_history else None
        group_score = score_event_group(events)
        results.append((
            {
                "entity": corp_history.entity,
                "corporation": current_corp,
                "alliance": current_alliance.entity if current_alliance else None,
                "entity_history": get_entity_history(corp_history, corp_alliance_histories),
                "priority_score": group_score,
            },
            events,
        ))

    results.sort(key=lambda x: x[0]["priority_score"], reverse=True)
    return results


def _get_region_grouped_information(
    snapshot: RecruitInteractionSnapshot,
):
    system_interaction_information = get_system_interaction_information(snapshot)

    region_constellation_system_information: dict[
        EveRegion, dict[EveConstellation, dict[EveSolarSystem, Any]]
    ] = {}

    for system, info in system_interaction_information.items():
        constellation = system.eve_constellation
        region = constellation.eve_region
        if region not in region_constellation_system_information:
            region_constellation_system_information[region] = {}
        if constellation not in region_constellation_system_information[region]:
            region_constellation_system_information[region][constellation] = {}
        region_constellation_system_information[region][constellation][system] = info

    return region_constellation_system_information


@login_required
@permission_required("memberaudit.finder_access")
def index(request: WSGIRequest) -> HttpResponse:
    """
    Index view
    :param request:
    :return:
    """

    selected_username = request.GET.get("selected_username")
    main_characters = _get_main_characters()
    if selected_username is None:
        if main_characters and main_characters[0]:
            selected_username = main_characters[0][0]
        else:
            return

    user_characters = _get_user_characters(selected_username)
    snapshot = collect_recruit_interaction_snapshot(user_characters)
    character_names = _get_character_names(user_characters)
    corp_histories = snapshot.corp_histories
    corp_ids = {
        entry.entity.id
        for profile in corp_histories.values()
        for entry in profile.corp_history
    }
    corp_alliance_histories = get_corp_alliance_histories(corp_ids)
    recruit_corp_ids, recruit_alliance_ids = _get_recruit_affiliation_ids(user_characters)
    score_all_interactions(
        snapshot.interactions,
        corp_histories,
        corp_alliance_histories,
        recruit_corp_ids,
        recruit_alliance_ids,
    )
    events = get_all_events(snapshot)
    context = {
        "main_characters": main_characters,
        "selected_username": selected_username,
        "user_characters": _map_character_attributes(user_characters),
        "blacklist_url": _get_blacklist_url(character_names),
        "eve411_url": _get_eve411_url(character_names),
        "character_grouped_events": _group_character_events(
            events,
            snapshot.character_ids,
            corp_histories,
            corp_alliance_histories,
        ),
        "region_grouped_information": _get_region_grouped_information(snapshot),
    }

    return render(request, "recruit/index.html", context)
