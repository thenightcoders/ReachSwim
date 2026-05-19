from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("orders/", views.orders, name="orders"),
    path("products/", views.products, name="products"),
    path("products/<int:pk>/stock/", views.product_update_stock, name="product_update_stock"),
    path("products/<int:pk>/toggle/", views.product_toggle_active, name="product_toggle_active"),
    path("settings/", views.settings_view, name="settings"),
    path("messages/", views.messages_view, name="messages"),
    path("messages/<int:pk>/read/", views.message_mark_read, name="message_mark_read"),
]
