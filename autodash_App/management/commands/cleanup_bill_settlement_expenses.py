"""Remove legacy `[Bill Settlement]` Expense rows.

These were auto-created by the old `daily_payment_targets` view to mirror
recurring-bill payments into the Expense ledger. Bill payments now live only
on `DailyPaymentTarget`, so the mirror rows are obsolete and cause double-
counting in P&L reports.

Usage:
    python manage.py cleanup_bill_settlement_expenses              # delete
    python manage.py cleanup_bill_settlement_expenses --dry-run    # report only
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum

from autodash_App.models import Expense


PREFIX = "[Bill Settlement]"


class Command(BaseCommand):
    help = "Delete legacy '[Bill Settlement]' Expense rows mirrored from DailyPaymentTarget payments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without changing the database.",
        )

    def handle(self, *args, **opts):
        qs = Expense.objects.filter(description__startswith=PREFIX)
        count = qs.count()

        if not count:
            self.stdout.write(self.style.SUCCESS("No '[Bill Settlement]' Expense rows found. Nothing to do."))
            return

        self.stdout.write(f"Found {count} '[Bill Settlement]' Expense row(s):")
        for row in qs.values("branch__name").annotate(total=Sum("amount")).order_by("branch__name"):
            branch = row["branch__name"] or "(no branch)"
            self.stdout.write(f"  - {branch}: GHS {row['total']:.2f}")

        total = qs.aggregate(s=Sum("amount"))["s"] or 0.0
        self.stdout.write(f"Total: GHS {total:.2f}")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run - no rows deleted."))
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} row(s)."))
