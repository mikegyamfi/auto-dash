# your_app/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from .models import RecurringExpense, CustomerBooking, Notification, OtherService, MaintenanceLog
from .models import Expense


# carwash/signals.py
from django.db.models.signals import pre_save, post_save, m2m_changed
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

    # Commission follows the same status rule as Revenue: only a completed or
    # on-credit job pays out.
    instance.sync_commission()
    _sync_other_service_arrears(instance)


def _sync_other_service_arrears(instance: OtherService):
    """
    An on-credit job is money owed, so it gets an Arrears row exactly like an
    on-credit service order does. Moving it off onCredit clears the row again —
    but never one that has already been settled, since that is a payment record.
    """
    from .models import Arrears

    existing = Arrears.objects.filter(other_service=instance).first()

    if instance.status == "onCredit":
        if existing is None:
            Arrears.objects.create(
                other_service=instance,
                branch=instance.branch,
                amount_owed=instance.amount or 0.0,
            )
        elif not existing.is_paid:
            # Keep the debt in step with an edited amount.
            if (existing.amount_owed or 0.0) != (instance.amount or 0.0):
                existing.amount_owed = instance.amount or 0.0
                existing.save(update_fields=["amount_owed"])
            if existing.branch_id != instance.branch_id:
                existing.branch = instance.branch
                existing.save(update_fields=["branch"])
    elif existing is not None and not existing.is_paid:
        existing.delete()


@receiver(m2m_changed, sender=OtherService.workers.through)
def other_service_workers_changed(sender, instance: OtherService, action, reverse, **kwargs):
    """
    The worker list is saved after the row itself (form.save_m2m), so the
    post_save above runs before anyone is on the job. Re-split once the team is
    known, and again whenever it's edited.
    """
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if reverse:
        # Changed from the Worker side — resync every job that was touched.
        for other_service in OtherService.objects.filter(pk__in=kwargs.get("pk_set") or []):
            other_service.sync_commission()
        return
    instance.sync_commission()


# ---------------------------------------------------------------------------
#  Utilities: a reading's expense should not outlive the reading
# ---------------------------------------------------------------------------

from django.db.models.signals import post_delete
from .models import UtilityReading


@receiver(post_delete, sender=UtilityReading)
def _drop_utility_reading_expense(sender, instance, **kwargs):
    """
    UtilityReading.expense is SET_NULL, so deleting the reading would otherwise
    strand the Expense row and overstate the branch's costs.
    """
    if instance.expense_id:
        Expense.objects.filter(pk=instance.expense_id).delete()

    # Its petty-cash reimbursement goes with it (CASCADE), but the balance
    # behind it still has to be rebuilt.
    account = PettyCashAccount.for_branch(instance.branch)
    if account is not None:
        account.recalculate()


# ---------------------------------------------------------------------------
#  Petty cash: a manual expense is cash leaving the tin
# ---------------------------------------------------------------------------

from .models import PettyCashAccount, PettyCashTransaction


def _expense_draws_petty_cash(expense):
    """
    Only expenses a person actually entered draw down the float.

    Auto-generated rows (utility usage) are a computed consumption cost — units
    burned x rate — not cash handed over. The cash for those left when the
    credit was bought, so charging the float again would double-count it.
    """
    return not expense.is_auto_generated


@receiver(post_save, sender=Expense)
def _sync_expense_to_petty_cash(sender, instance: Expense, created, **kwargs):
    """
    Mirror a manual expense onto the branch's petty cash float. Idempotent: an
    edited amount moves the existing movement rather than stacking a new one,
    and reclassifying an expense as auto-generated removes it from the float.
    """
    account = PettyCashAccount.for_branch(instance.branch)
    existing = PettyCashTransaction.objects.filter(expense=instance).first()

    # No float open for this branch, or this expense shouldn't touch it.
    if account is None or not account.is_active or not _expense_draws_petty_cash(instance):
        if existing is not None:
            existing.delete()
        return

    if existing is None:
        PettyCashTransaction.objects.create(
            account=account,
            branch=instance.branch,
            kind=PettyCashTransaction.KIND_EXPENSE,
            amount=instance.amount or 0.0,
            expense=instance,
            date=instance.date,
            recorded_by=instance.user,
        )
        return

    # Keep the movement in step with the expense it mirrors.
    changed = False
    for field, value in (
        ("amount", abs(instance.amount or 0.0)),
        ("date", instance.date),
        ("branch_id", instance.branch_id),
    ):
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed = True
    if existing.account_id != account.id:
        existing.account = account
        changed = True
    if changed:
        existing.save()


@receiver(post_delete, sender=Expense)
def _drop_expense_petty_cash(sender, instance: Expense, **kwargs):
    """
    Deleting an expense returns the cash to the float. The OneToOne is CASCADE,
    so the row goes on its own; this just rebuilds the balance behind it.
    """
    account = PettyCashAccount.for_branch(instance.branch)
    if account is not None:
        account.recalculate()


# ---------------------------------------------------------------------------
#  Utility usage is reimbursed into petty cash
# ---------------------------------------------------------------------------

@receiver(post_save, sender=UtilityReading)
def _reimburse_utility_usage_to_petty_cash(sender, instance: UtilityReading, created, **kwargs):
    """
    The cash value of the utility consumed is handed straight back to the branch
    so they can spend it, rather than waiting for a reimbursement run.

    The usage Expense still stands as the P&L cost, and deliberately does NOT
    draw the float down (it is auto-generated) — otherwise the +X reimbursement
    and the -X expense would cancel out and the branch would be no better off.

    Idempotent: a corrected reading moves its own reimbursement rather than
    stacking a second one, and `propagate_forward()` re-saves every later
    reading, so their reimbursements follow the repaired trail too.
    """
    account = PettyCashAccount.for_branch(instance.branch)
    existing = PettyCashTransaction.objects.filter(utility_reading=instance).first()

    amount = instance.expense_amount  # usage x cost_per_unit, rounded
    should_exist = account is not None and account.is_active and amount > 0

    if not should_exist:
        if existing is not None:
            existing.delete()
        return

    if existing is None:
        PettyCashTransaction.objects.create(
            account=account,
            branch=instance.branch,
            kind=PettyCashTransaction.KIND_REIMBURSEMENT,
            amount=amount,
            utility_reading=instance,
            date=instance.date,
            recorded_by=instance.entered_by,
        )
        return

    changed = False
    for field, value in (
        ("amount", amount),
        ("date", instance.date),
        ("branch_id", instance.branch_id),
    ):
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed = True
    if existing.account_id != account.id:
        existing.account = account
        changed = True
    if changed:
        existing.save()
