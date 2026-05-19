"""
Shop views — pure HTTP layer.

shop_section: homepage section partial (included in pages app template).
product_list: full shop page with filter support.
"""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .models import Product, ProductCategory, ShopSettings


def shop_section(request: HttpRequest) -> HttpResponse:
    """Render the shop section for the homepage."""
    settings = ShopSettings.load()
    categories = ProductCategory.objects.all()
    products = Product.objects.filter(is_active=True).select_related("category")

    return render(request, "shop/partials/shop_section.html", {
        "shop_settings": settings,
        "categories": categories,
        "products": products,
    })
