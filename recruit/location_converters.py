# Alliance Auth (External Libs)
from eveuniverse.models import EveSolarSystem

from .interaction_collector import (
    RecruitInteractionSnapshot,
    SystemInformation,
)


def get_system_interaction_information(
    snapshot: RecruitInteractionSnapshot,
) -> dict[EveSolarSystem, SystemInformation]:
    """Gather per-system interaction data for a set of characters.

    This returns location/system aggregates from the shared recruit snapshot.

    Args:
        source: queryset of ``Character`` instances or a pre-built snapshot.

    Returns:
        mapping from ``EveSolarSystem`` to ``SystemInformation``.

    """
    return snapshot.system_information
