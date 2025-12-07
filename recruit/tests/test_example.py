"""
Recruit Test
"""

# Django
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter


class RecruitIndexViewTests(TestCase):
    """Tests for the Recruit index view."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="main-user")
        permission = Permission.objects.get(
            codename="basic_access",
            content_type__app_label="recruit",
        )
        self.user.user_permissions.add(permission)
        self.client.force_login(self.user)

        main_character = self._create_character(character_id=1100, name="Main Pilot")
        profile = self.user.profile
        profile.main_character = main_character
        profile.save(update_fields=["main_character"])

        alt_character = self._create_character(character_id=1200, name="Alt Pilot")
        self.primary_ownership = CharacterOwnership.objects.create(
            user=self.user,
            character=alt_character,
            owner_hash="owner-hash-1",
        )

        other_user = User.objects.create_user(username="other-user")
        other_main = self._create_character(character_id=2100, name="Other Main")
        other_profile = other_user.profile
        other_profile.main_character = other_main
        other_profile.save(update_fields=["main_character"])

        other_character = self._create_character(character_id=2200, name="Other Alt")
        self.secondary_ownership = CharacterOwnership.objects.create(
            user=other_user,
            character=other_character,
            owner_hash="owner-hash-2",
        )

    def _create_character(self, *, character_id: int, name: str) -> EveCharacter:
        """Helper to create an EveCharacter with minimal required fields."""

        return EveCharacter.objects.create(
            character_id=character_id,
            character_name=name,
            corporation_id=character_id + 10,
            corporation_name=f"Corporation {character_id}",
            corporation_ticker=f"C{character_id}"[:5],
            alliance_id=None,
            alliance_name="",
            alliance_ticker="",
            faction_id=None,
            faction_name="",
        )

    def test_index_lists_character_ownerships_labelled_by_main_character(self):
        response = self.client.get(reverse("recruit:index"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("character_ownerships", response.context)
        self.assertEqual(
            response.context["character_ownerships"],
            [
                {
                    "id": str(self.primary_ownership.pk),
                    "main_character_name": "Main Pilot",
                    "character_name": "Alt Pilot",
                },
                {
                    "id": str(self.secondary_ownership.pk),
                    "main_character_name": "Other Main",
                    "character_name": "Other Alt",
                },
            ],
        )
        self.assertContains(response, "Main Pilot - Alt Pilot")
        self.assertContains(response, "Other Main - Other Alt")
