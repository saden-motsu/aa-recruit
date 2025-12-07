"""
Recruit Test
"""

# Django
from django.test import TestCase


class TestRecruit(TestCase):
    """
    TestRecruit
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Test setup
        :return:
        :rtype:
        """

        super().setUpClass()

    def test_recruit(self):
        """
        Dummy test function
        :return:
        :rtype:
        """

        self.assertEqual(True, True)
