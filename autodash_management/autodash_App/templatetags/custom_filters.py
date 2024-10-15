# templatetags/custom_filters.py

from django import template

register = template.Library()

@register.filter
def pluck(queryset, key):
    return [item.get(key) for item in queryset]

@register.filter
def pluck_worker_names(workers_ratings):
    return [f"{item['user__first_name']} {item['user__last_name']}" for item in workers_ratings]

