from django.urls import path
from .views import LegalPageView, contact_view

app_name = "legal"

urlpatterns = [
    path("contact/", contact_view, name="contact"),
    path("<slug:slug>/", LegalPageView.as_view(), name="page"),
]
