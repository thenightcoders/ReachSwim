from django import template

register = template.Library()
# All pence → pounds formatting lives in apps.payments.templatetags.payment_tags.
# Load that library in templates: {% load payment_tags %}
