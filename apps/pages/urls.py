from django.urls import path
from .views import HomepageView

app_name = "pages"

urlpatterns = [
    path("", HomepageView.as_view(), name="home"),
]
