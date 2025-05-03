# your_app/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import RecurringExpense
from .models import Expense


@receiver(post_save, sender=RecurringExpense)
def mint_recurring_expense_today(sender, instance, created, **kwargs):
    """
    Whenever a RecurringExpense is created or updated,
    if it applies today, ensure there's an Expense row for today.
    """
    today = timezone.localdate()
    if instance.applies_today(today):
        Expense.objects.get_or_create(
            branch=instance.branch,
            description=f"[Recurring] {instance.description}",
            amount=instance.amount,
            date=today,
            defaults={'user': None}
        )
