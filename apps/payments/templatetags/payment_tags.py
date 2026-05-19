"""Template filters for formatting pence as pounds."""
from django import template

register = template.Library()


@register.filter
def pence_to_pounds(value):
    """Convert pence (int) to £X.XX string."""
    try:
        return f"£{int(value) / 100:.2f}"
    except (TypeError, ValueError):
        return "£0.00"
