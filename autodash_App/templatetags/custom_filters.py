# templatetags/custom_filters.py
import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def pluck(queryset, key):
    return [item.get(key) for item in queryset]


@register.filter
def pluck_worker_names(workers_ratings):
    return [f"{item['user__first_name']} {item['user__last_name']}" for item in workers_ratings]


@register.filter
def dictlookup(value, key):
    """
    Usage in templates: {{ mydict|dictlookup:mykey }}
    Returns mydict[mykey] or None if it doesn't exist.
    """
    if value is None:
        return None
    return value.get(key, None)


@register.filter
def json_script(value, element_id):
    """Outputs a <script> tag with JSON-encoded data."""
    json_data = json.dumps(value)
    return mark_safe(f'<script id="{element_id}" type="application/json">{json_data}</script>')


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)








