"""Template filters for formatting pence as the configured currency."""
from django import template

register = template.Library()


def _currency_symbol() -> str:
    """Return the site-configured currency symbol (cached via SiteConfig.load)."""
    from apps.pages.models import SiteConfig
    return SiteConfig.load().currency_symbol


@register.filter
def pence_to_pounds(value):
    """Convert smallest-unit integer to currency string using the site currency."""
    symbol = _currency_symbol()
    try:
        return f"{symbol}{int(value) / 100:.2f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


@register.filter
def pence_to_decimal(value):
    """Convert pence (int) to X.XX string (no £ sign). For use in input values."""
    try:
        return f"{int(value) / 100:.2f}"
    except (TypeError, ValueError):
        return "0.00"
