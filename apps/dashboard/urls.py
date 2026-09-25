from django.urls import path

from . import registry, views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),

    # Bookings
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/bulk/", views.bookings_bulk, name="bookings_bulk"),
    path("bookings/create/", views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="booking_edit"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
    path("bookings/<int:pk>/send-reminder/", views.send_reminder, name="send_reminder"),
    path("bookings/<int:pk>/refund/", views.booking_issue_refund, name="booking_issue_refund"),

    # Orders
    path("orders/", views.orders, name="orders"),
    path("orders/bulk/", views.orders_bulk, name="orders_bulk"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/refund/", views.order_refund, name="order_refund"),
    path("orders/<int:pk>/expire/", views.order_expire, name="order_expire"),
    path("orders/<int:order_pk>/items/<int:item_pk>/ship/", views.order_item_ship, name="order_item_ship"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order_delete"),

    # Products
    path("products/", views.products, name="products"),
    path("products/bulk/", views.products_bulk, name="products_bulk"),
    path("products/create/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/stock/", views.product_update_stock, name="product_update_stock"),
    path("products/<int:pk>/toggle/", views.product_toggle_active, name="product_toggle_active"),

    # Messages
    path("messages/", views.messages_view, name="messages"),
    path("messages/bulk/", views.messages_bulk, name="messages_bulk"),
    path("messages/<int:pk>/", views.message_detail, name="message_detail"),
    path("messages/<int:pk>/read/", views.message_mark_read, name="message_mark_read"),
    path("messages/<int:pk>/spam/", views.message_mark_spam, name="message_mark_spam"),
    path("messages/<int:pk>/check/", views.message_check, name="message_check"),
    path("messages/<int:pk>/ban/", views.message_ban, name="message_ban"),
    path("messages/<int:pk>/delete/", views.message_delete, name="message_delete"),

    # People
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("users/<int:pk>/login-link/", views.user_send_login_link, name="user_send_login_link"),
    path("users/<int:pk>/password/", views.user_set_password, name="user_set_password"),

    # Pricing & package grants
    path("pricing/", views.pricing, name="pricing"),
    path("package-credits/grant/", views.packagepurchase_grant, name="packagepurchase_grant"),

    # Settings & account
    path("settings/", views.settings_view, name="settings"),
    path("account/", views.account_view, name="account"),

    # Google Calendar OAuth
    path("google-calendar/connect/", views.gcal_connect, name="gcal_connect"),
    path("google-calendar/callback/", views.gcal_callback, name="gcal_callback"),
    path("google-calendar/disconnect/", views.gcal_disconnect, name="gcal_disconnect"),
    path("google-calendar/sync/", views.gcal_sync, name="gcal_sync"),
] + registry.urlpatterns()
