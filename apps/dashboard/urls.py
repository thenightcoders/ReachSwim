from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/create/", views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="booking_edit"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
    path("bookings/<int:pk>/send-reminder/", views.send_reminder, name="send_reminder"),
    path("bookings/<int:pk>/refund/", views.booking_issue_refund, name="booking_issue_refund"),
    path("orders/", views.orders, name="orders"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/refund/", views.order_refund, name="order_refund"),
    path("orders/<int:order_pk>/items/<int:item_pk>/ship/", views.order_item_ship, name="order_item_ship"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order_delete"),
    path("products/", views.products, name="products"),
    path("products/create/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/stock/", views.product_update_stock, name="product_update_stock"),
    path("products/<int:pk>/toggle/", views.product_toggle_active, name="product_toggle_active"),
    path("account/", views.account_view, name="account"),
    path("settings/", views.settings_view, name="settings"),
    path("messages/", views.messages_view, name="messages"),
    path("messages/<int:pk>/read/", views.message_mark_read, name="message_mark_read"),

    # Locations
    path("locations/", views.location_list, name="location_list"),
    path("locations/create/", views.location_create, name="location_create"),
    path("locations/<int:pk>/edit/", views.location_edit, name="location_edit"),
    path("locations/<int:pk>/delete/", views.location_delete, name="location_delete"),

    # Session Types
    path("sessiontypes/", views.sessiontype_list, name="sessiontype_list"),
    path("sessiontypes/create/", views.sessiontype_create, name="sessiontype_create"),
    path("sessiontypes/<int:pk>/edit/", views.sessiontype_edit, name="sessiontype_edit"),
    path("sessiontypes/<int:pk>/delete/", views.sessiontype_delete, name="sessiontype_delete"),
    path("sessiontypes/<int:pk>/pricing/", views.sessiontype_pricing_update, name="sessiontype_pricing_update"),

    # Schedules
    path("schedules/", views.schedule_list, name="schedule_list"),
    path("schedules/create/", views.schedule_create, name="schedule_create"),
    path("schedules/<int:pk>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedules/<int:pk>/delete/", views.schedule_delete, name="schedule_delete"),

    # Users
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),

    # Google Calendar OAuth
    path("google-calendar/connect/", views.gcal_connect, name="gcal_connect"),
    path("google-calendar/callback/", views.gcal_callback, name="gcal_callback"),
    path("google-calendar/disconnect/", views.gcal_disconnect, name="gcal_disconnect"),
    path("google-calendar/sync/", views.gcal_sync, name="gcal_sync"),
]
