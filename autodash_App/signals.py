# your_app/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from .models import RecurringExpense, CustomerBooking, Notification
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

@receiver(pre_save, sender=ServiceRenderedOrder)
def _remember_old_status(sender, instance, **kwargs):
    if instance.pk:
        instance._old_status = sender.objects.get(pk=instance.pk).status
    else:
        instance._old_status = None


@receiver(post_save, sender=ServiceRenderedOrder)
def _sync_revenue(sender, instance, created, **kwargs):
    old = instance._old_status
    new = instance.status

    # 1) Only create/update revenue when status just became 'completed'
    if instance.status == "completed":
        Revenue.objects.update_or_create(
            service_rendered=instance,
            defaults={
                "branch": instance.branch,
                "amount": instance.total_amount,
                "final_amount": instance.final_amount,
                "discount": instance.discount_value,
                "user": getattr(instance, "updated_by", None),
                "date": timezone.now().date(),
            },
        )

    else:
        Revenue.objects.filter(service_rendered=instance).delete()


@receiver(post_save, sender=CustomerBooking)
def booking_created_worker_notification(sender, instance: CustomerBooking, created, **kwargs):
    """
    Create a single broadcast-style notification for WORKERS when a booking is created.
    Not tied to a user. Your templates can show it to workers/branch-admins.
    """
    if not created:
        return

    booking = instance
    branch = booking.branch  # may be None

    # Human text
    vehicle_name = booking.vehicle.car_name() if booking.vehicle else "a vehicle"
    services_list = list(booking.services.values_list("service_type", flat=True))
    services_text = ", ".join(services_list) if services_list else "selected service(s)"
    dt_text = (
        timezone.localtime(booking.scheduled_at).strftime("%Y-%m-%d %H:%M")
        if booking.scheduled_at else "the scheduled time"
    )
    branch_name = branch.name if branch else "—"

    # Link to booking detail (adjust URL name if different)
    try:
        target_url = reverse("customer_booking_detail", kwargs={"pk": booking.pk})
    except Exception as e:
        print(e)
        target_url = None

    # Create exactly ONE notification, audience=branch (i.e., for workers)
    Notification.objects.create(
        branch=branch,                        # lets you filter per-branch in the UI
        title="New Booking Received",
        message=f"{services_text} for {vehicle_name} on {dt_text} at {branch_name}.",
        level=Notification.LEVEL_INFO,
        target_url=target_url,
    )


