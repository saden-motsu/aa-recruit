# Standard Library
from collections import defaultdict

# Third Party
from memberaudit.managers.characters import CharacterQuerySet
from memberaudit.models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterLocation,
    CharacterMiningLedgerEntry,
    CharacterPlanet,
    CharacterWalletTransaction,
    Location,
)

# Alliance Auth (External Libs)
from eveuniverse.models import EveSolarSystem, EveType


class LocationInformation:
    def __init__(self):
        self.clone_implants: dict[Character, list[EveType]] | None = None
        self.transactions: list[CharacterWalletTransaction] = []
        self.contracts: set[CharacterContract] = set()
        self.assets: list[CharacterAsset] = []
        self.characters_home: set[Character] = set()


class SystemInformation:
    def __init__(self):
        self.location_information: dict[Location, LocationInformation] = defaultdict(
            LocationInformation
        )
        self.mining_ledger_entries: list[CharacterMiningLedgerEntry] = []
        self.planets: list[CharacterPlanet] = []
        self.characters_in_space: set[Character] = set()


def get_system_interaction_information(
    character_query_set: CharacterQuerySet,
) -> dict[EveSolarSystem, SystemInformation]:
    system_information: dict[EveSolarSystem, SystemInformation] = defaultdict(
        SystemInformation
    )

    def get_character_location_information(
        character_location: CharacterLocation,
    ) -> LocationInformation | None:
        location_safe = character_location.location_safe()
        if not location_safe or not location_safe.eve_solar_system:
            return None
        return system_information[location_safe.eve_solar_system].location_information[
            location_safe
        ]

    def get_location_information(
        location: Location | None,
    ) -> LocationInformation | None:
        if location and location.eve_solar_system:
            return system_information[location.eve_solar_system].location_information[
                location
            ]
        return None

    for character in character_query_set:
        if character.clone_info and (
            location_information := get_location_information(
                character.clone_info.home_location
            )
        ):
            location_information.characters_home.add(character)

        if location_information := get_character_location_information(
            character.location
        ):
            if location_information.clone_implants is None:
                location_information.clone_implants = {}
            location_information.clone_implants[character] = [
                x.eve_type for x in character.implants.all()
            ]

        for jump_clone in character.jump_clones.all():
            if location_information := get_location_information(jump_clone.location):
                if location_information.clone_implants is None:
                    location_information.clone_implants = {}
                location_information.clone_implants[jump_clone.character] = [
                    x.eve_type for x in jump_clone.implants.all()
                ]

        for wallet_transaction in character.wallet_transactions.all():
            get_location_information(wallet_transaction.location).transactions.append(
                wallet_transaction
            )

        for contract in character.contracts.all():
            if location_information := get_location_information(
                contract.start_location
            ):
                location_information.contracts.add(contract)
            if location_information := get_location_information(contract.end_location):
                location_information.contracts.add(contract)

        for asset in character.assets.all():
            if location_information := get_location_information(asset.location):
                location_information.assets.append(asset)

        for mining_ledger_entry in character.mining_ledger.all():
            system_information[
                mining_ledger_entry.eve_solar_system
            ].mining_ledger_entries.append(mining_ledger_entry)

        for planet in character.planets.all():
            if planet.eve_planet and planet.eve_planet.eve_solar_system:
                system_information[planet.eve_planet.eve_solar_system].planets.append(
                    planet
                )

    return system_information
