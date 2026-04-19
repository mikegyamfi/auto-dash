# your_app/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from .models import RecurringExpense, CustomerBooking, Notification, OtherService, MaintenanceLog
from .models import Expense


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


@receiver(post_save, sender=MaintenanceLog)
def maintenance_created_notification(sender, instance: MaintenanceLog, created, **kwargs):
    """Branch-scoped notification when a new maintenance log is filed."""
    if not created:
        return

    branch = instance.branch
    reporter = instance.reported_by.get_full_name() if instance.reported_by else "Someone"
    reporter = reporter.strip() or (instance.reported_by.username if instance.reported_by else "Someone")
    priority_display = instance.get_priority_display()

    try:
        target_url = reverse("maintenance_detail", kwargs={"pk": instance.pk})
    except Exception as e:
        print(e)
        target_url = None

    # Map priority to notification level.
    level = {
        MaintenanceLog.PRIORITY_HIGH: Notification.LEVEL_WARNING,
        MaintenanceLog.PRIORITY_MED: Notification.LEVEL_INFO,
        MaintenanceLog.PRIORITY_LOW: Notification.LEVEL_INFO,
    }.get(instance.priority, Notification.LEVEL_INFO)

    Notification.objects.create(
        branch=branch,
        title=f"New Maintenance Log — {instance.title}",
        message=f"{reporter} logged a {priority_display}-priority issue at {branch.name}.",
        level=level,
        target_url=target_url,
    )


@receiver(post_save, sender=OtherService)
def other_service_sync_revenue(sender, instance: OtherService, created, **kwargs):
    """
    Keep Revenue in sync for OtherService via Revenue.other_service:

      - If status == completed:
          - create Revenue once if not present
          - else update branch/user/amount if they changed
      - If status != completed:
          - delete existing Revenue (if any)
    """
    # Find any existing Revenue linked to this OtherService
    rev = Revenue.objects.filter(other_service=instance).first()

    if instance.status == "completed":
        if rev is None:
            rev = Revenue.objects.create(
                other_service=instance,       # <-- the new link
                branch=instance.branch,
                amount=instance.amount,
                final_amount=instance.amount,
                discount=0.0,
                user=instance.user,
                date=timezone.now().date(),
            )
        else:
            changed = False
            if (rev.amount or 0) != instance.amount or (rev.final_amount or 0) != instance.amount:
                rev.amount = instance.amount
                rev.final_amount = instance.amount
                changed = True
            if rev.branch_id != instance.branch_id:
                rev.branch = instance.branch
                changed = True
            if rev.user_id != instance.user_id:
                rev.user = instance.user
                changed = True
            if changed:
                rev.save()
    else:
        if rev:
            rev.delete()


