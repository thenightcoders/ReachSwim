"""
Shop context processor — injects shop_settings into every template.
"""
from .models import ShopSettings


def shop_context(request):
    return {
        "shop_settings": ShopSettings.load(),
    }
