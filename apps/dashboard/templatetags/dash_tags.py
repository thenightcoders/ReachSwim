"""Template helpers for the dashboard's generic list/form templates."""
from django import template

register = template.Library()


@register.filter
def affix(bound_field):
    """Currency symbol for MoneyField inputs, '' otherwise."""
    from apps.dashboard.forms import MoneyField
    if isinstance(bound_field.field, MoneyField):
        from apps.pages.models import SiteConfig
        return SiteConfig.load().currency_symbol
    return ""


@register.simple_tag
def cell(obj, column):
    """Resolve a list column (attribute, method, or callable) against a row."""
    return column.value(obj)


@register.filter
def initial(value):
    """First letter, upper-cased — for avatar and thumbnail placeholders."""
    return (str(value or "?").strip()[:1] or "?").upper()
