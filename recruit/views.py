"""App Views"""

# Django
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import render

# Alliance Auth
from allianceauth.authentication.models import UserProfile


def _get_main_characters() -> list[(int, str)]:
    """
    Gets a list of all main character names.
    """

    return (
        UserProfile.objects.exclude(main_character__isnull=True)
        .order_by("user__date_joined")
        .values_list("user__username", "main_character__character_name")
    )


@login_required
@permission_required("recruit.basic_access")
def index(request: WSGIRequest) -> HttpResponse:
    """
    Index view
    :param request:
    :return:
    """

    context = {
        "main_characters": _get_main_characters(),
    }

    return render(request, "recruit/index.html", context)
