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


# carwash/signals.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import ServiceRenderedOrder, Revenue

TERMINAL = {"completed", "onCredit"}


@receiver(pre_save, sender=ServiceRenderedOrder)
def _remember_old_status(sender, instance, **kwargs):
    if instance.pk:
        instance._old_status = sender.objects.get(pk=instance.pk).status
    else:
        instance._old_status = None


@receiver(post_save, sender=ServiceRenderedOrder)
def _sync_revenue(sender, instance, created, **kwargs):
    was_terminal = instance._old_status in TERMINAL
    is_terminal = instance.status in TERMINAL

    if is_terminal:
        Revenue.objects.update_or_create(
            service_rendered=instance,
            defaults=dict(
                branch=instance.branch,
                amount=instance.total_amount,
                final_amount=instance.final_amount,
                user=getattr(instance, "updated_by", None),
                date=timezone.now(),
            ),
        )
    elif was_terminal and not is_terminal:
        Revenue.objects.filter(service_rendered=instance).delete()
