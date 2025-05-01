from django.utils import timezone
from django.core.exceptions import ValidationError


def assert_unique_active_subscription(customer, subscription):
    from .models import CustomerSubscription
    clash = CustomerSubscription.objects.filter(
        customer=customer,
        subscription=subscription,
    ).exists()
    if clash:
        raise ValidationError(
            f"{customer} already holds an active '{subscription}' subscription."
        )
