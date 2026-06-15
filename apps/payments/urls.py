from django.urls import path
from apps.payments import views

app_name = "payments"

urlpatterns = [
    # Cart (HTMX)
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/add-product/", views.cart_add_product, name="cart_add_product"),
    path("cart/update-qty/", views.cart_update_qty, name="cart_update_qty"),
    path("cart/remove/", views.cart_remove, name="cart_remove"),
    path("cart/clear/", views.cart_clear, name="cart_clear"),
    path("cart/voucher/apply/", views.cart_apply_voucher, name="cart_apply_voucher"),
    path("cart/voucher/remove/", views.cart_remove_voucher, name="cart_remove_voucher"),
    path("cart/", views.cart_view, name="cart_view"),
    path("cart/badge/", views.cart_badge, name="cart_badge"),

    # Checkout
    path("checkout/", views.checkout_page, name="checkout"),
    path("checkout/pay/", views.checkout, name="checkout_pay"),

    # Post-payment
    path("payments/success/", views.payment_success, name="success"),
    path("payments/cancel/", views.payment_cancel, name="cancel"),

    # Stripe webhook
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),

    # Payment reminder resume link (from email)
    path("pay/resume/<str:token>/", views.resume_payment, name="resume_payment"),
]
