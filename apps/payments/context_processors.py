"""
Payment context processors — inject cart count into every template.
"""
from apps.payments.services.cart import cart_count


def cart_context(request):
    return {
        "cart_count": cart_count(request),
    }
