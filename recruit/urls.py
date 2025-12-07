"""App URLs"""

# Django
from django.urls import path

# AA Recruit App
# AA Rercuit App
from recruit import views

app_name: str = "recruit"  # pylint: disable=invalid-name

urlpatterns = [
    path("", views.index, name="index"),
]
