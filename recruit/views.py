"""App Views"""

# Standard Library
from collections.abc import Iterable
from typing import Any

# Third Party
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


def _get_main_characters() -> list[str, str]:
    """
    Gets a list of all main character names.
    """

    return (
        UserProfile.objects.exclude(main_character__isnull=True)
        .order_by("user__date_joined")
        .values_list("user__username", "main_character__character_name")
    )


def _get_user_characters(selected_username: str | None) -> Iterable[dict[str, Any]]:
    if not selected_username:
        return []

    keymap: dict[str, str] = {
        "eve_character__character_id": "id",
        "eve_character__character_name": "name",
        "wallet_balance__total": "wallet_isk",
        "skillpoints__total": "total_sp",
    }

    characters_values = (
        Character.objects.filter(
            eve_character__character_ownership__user__username=selected_username
        )
        .order_by("skillpoints__total")
        .values(*keymap.keys())
    )

    for character_values in characters_values:
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

    print(list(_get_user_characters(selected_username)))
    context = {
        "main_characters": main_characters,
        "selected_username": selected_username,
        "user_characters": _get_user_characters(selected_username),
    }

    return render(request, "recruit/index.html", context)
