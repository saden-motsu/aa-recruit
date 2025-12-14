"""App Views"""

# Standard Library
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models.character_sections_1 import CharacterAsset
from memberaudit.models.characters import Character

# Django
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import F, FloatField, Sum
from django.http import HttpResponse
from django.shortcuts import render

# Alliance Auth
from allianceauth.authentication.models import UserProfile

from .character_event import CharacterEvent
from .character_event_converters import get_all_events


def _get_main_characters() -> list[str, str]:
    """
    Gets a list of all main character names.
    """

    return (
        UserProfile.objects.exclude(main_character__isnull=True)
        .order_by("user__date_joined")
        .values_list("user__username", "main_character__character_name")
    )


def _get_user_characters(selected_username: str | None) -> CharacterQuerySet:
    return Character.objects.filter(
        eve_character__character_ownership__user__username=selected_username
    ).order_by("skillpoints__total")


def _map_character_attributes(
    character_query: CharacterQuerySet,
) -> Iterable[dict[str, Any]]:
    keymap: dict[str, str] = {
        "eve_character__character_id": "id",
        "eve_character__character_name": "name",
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


def _group_character_events(
    character_events: Iterable[CharacterEvent],
) -> list[tuple[str, list[dict]]]:
    grouped_events = defaultdict(list)

    for character_event in character_events:
        grouped_events[
            (character_event.other_character_id, character_event.other_character_name)
        ].append(character_event)

    results: list[tuple[str, str, list[CharacterEvent]]] = []
    for (character_id, character_name), character_events in grouped_events.items():
        character_events.sort(
            key=lambda x: (x.timestamp is None, x.timestamp or datetime.max)
        )
        evewho = f"https://evewho.com/character/{character_id}"
        results.append((character_name, evewho, character_events))

    return results


@login_required
@permission_required("recruit.basic_access")
def index(request: WSGIRequest) -> HttpResponse:
    """
    Index view
    :param request:
    :return:
    """

    selected_username = request.GET.get("selected_username")
    main_characters = _get_main_characters()
    if selected_username is None and main_characters:
        selected_username = main_characters[0][0]

    user_characters = _get_user_characters(selected_username)
    events = get_all_events(user_characters)
    character_names = _get_character_names(user_characters)
    context = {
        "main_characters": main_characters,
        "selected_username": selected_username,
        "user_characters": _map_character_attributes(user_characters),
        "blacklist_url": _get_blacklist_url(character_names),
        "eve411_url": _get_eve411_url(character_names),
        "character_grouped_events": _group_character_events(events),
    }

    return render(request, "recruit/index.html", context)
