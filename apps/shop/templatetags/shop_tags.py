"""
Shop template tags.

{% load shop_tags %}
{% shop_section %}   — renders the full shop section partial inline.

Keeps the shop app responsible for its own data fetching.  The pages app
never needs to import shop models.
"""
from django import template

from apps.shop.models import Product, ProductCategory, ShopSettings

register = template.Library()


@register.inclusion_tag("shop/partials/shop_section.html", takes_context=True)
def shop_section(context):
    """Render the shop section with live product data."""
    return {
        "shop_settings": ShopSettings.load(),
        "categories": ProductCategory.objects.all(),
        "products": Product.objects.filter(is_active=True).select_related("category"),
        # Forward request so the template can use {% csrf_token %} etc.
        "request": context.get("request"),
    }
