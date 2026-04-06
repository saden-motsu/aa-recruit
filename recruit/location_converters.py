# Standard Library
from collections import defaultdict
from typing import Any

# Alliance Auth (External Libs)
from eveuniverse.models import EveSolarSystem

from .interaction import Interaction
from .interaction_collector import RecruitInteractionSnapshot


def get_system_interaction_information(
    snapshot: RecruitInteractionSnapshot,
) -> dict[EveSolarSystem, dict[str, Any]]:
    """Group interactions by system, then by location and kind."""
    results: dict[EveSolarSystem, dict[str, Any]] = {}

    for interaction in snapshot.interactions:
        solar_system = interaction.solar_system or getattr(
            interaction.location, "eve_solar_system", None
        )
        if solar_system is None:
            continue

        system_information = results.setdefault(
            solar_system,
            {
                "system_interactions": defaultdict(list),
                "location_interactions": defaultdict(lambda: defaultdict(list)),
            },
        )

        if interaction.location is None:
            system_information["system_interactions"][interaction.kind].append(
                interaction
            )
        else:
            system_information["location_interactions"][interaction.location][
                interaction.kind
            ].append(interaction)

    for system_information in results.values():
        system_information["system_interactions"] = _finalize_grouped_interactions(
            system_information["system_interactions"]
        )
        system_information["location_interactions"] = {
            location: _finalize_grouped_interactions(interactions_by_kind)
            for location, interactions_by_kind in system_information[
                "location_interactions"
            ].items()
        }

    return results


def _finalize_grouped_interactions(
    interactions_by_kind: dict[str, list[Interaction]],
) -> dict[str, list[Interaction]]:
    finalized = {
        kind: list(interactions) for kind, interactions in interactions_by_kind.items()
    }
    if "asset" in finalized:
        finalized["asset"].sort(
            key=lambda interaction: interaction.isk_value or 0, reverse=True
        )
        finalized["asset_total_value"] = sum(
            interaction.isk_value or 0 for interaction in finalized["asset"]
        )
    return finalized
