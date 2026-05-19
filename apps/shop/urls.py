from django.urls import path
from . import views

app_name = "shop"

urlpatterns = [
    path("shop/section/", views.shop_section, name="section"),
]
