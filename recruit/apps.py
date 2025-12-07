"""App Configuration"""

# Django
from django.apps import AppConfig

# AA Recruit App
from recruit import __version__


class RecruitConfig(AppConfig):
    """App Config"""

    name = "recruit"
    label = "recruit"
    verbose_name = f"Recruit App v{__version__}"
