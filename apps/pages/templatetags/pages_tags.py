from django import template

register = template.Library()


@register.filter
def pence_to_pounds(value):
    """Convert pence (int) to pounds string, e.g. 1500 → '15.00'."""
    try:
        return f"{int(value) / 100:.2f}"
    except (ValueError, TypeError):
        return "0.00"
