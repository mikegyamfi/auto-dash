"""
Rebuild the remittance carry chain from the rows that actually exist.

A remittance row is a running balance: what a day leaves unpaid becomes the next
day's `brought_forward`. That chain was only ever written once, at row creation,
and never recomputed — so a payment recorded against an old day, a target edited
after the fact, or a day opened out of order left every later row holding a
figure that no longer followed from the one before it.

This recomputes `brought_forward` and `carried_forward` for every row, per
branch, oldest first. Unlike `reset_remittance_outstanding` it **never touches
`target_amount`**, so each day keeps the target it actually ran under, and it
never touches a `RemittancePayment` — what was handed over is what was handed
over.

    python manage.py repair_remittance_chain --dry-run
    python manage.py repair_remittance_chain --from 2026-09-01
    python manage.py repair_remittance_chain --branch 3

`--from` starts the chain fresh at that date, treating everything before it as
closed. That is how to drop a backlog accumulated before the branch really
started remitting, without inventing a target for those days.

Days with no row are left alone. A day that was never opened was never owed.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autodash_App.models import Branch, DailyRemittance


class Command(BaseCommand):
    help = "Rebuild brought_forward / carried_forward across each branch's remittance rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--branch", type=int, default=None,
            help="Limit to one branch id.",
        )
        parser.add_argument(
            "--from", dest="start", default=None, metavar="YYYY-MM-DD",
            help="Start the chain here, treating anything earlier as closed.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        start = None
        if opts["start"]:
            try:
                start = datetime.strptime(opts["start"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--from must be YYYY-MM-DD")

        branches = Branch.objects.all()
        if opts["branch"]:
            branches = branches.filter(id=opts["branch"])
            if not branches.exists():
                raise CommandError(f"No branch with id {opts['branch']}")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nRemittance chain repair{'  (dry run)' if dry else ''}"
        ))

        grand_before = grand_after = 0.0
        total_changed = 0

        for branch in branches.order_by("name"):
            rows = DailyRemittance.objects.filter(branch=branch).order_by("date")
            if start:
                rows = rows.filter(date__gte=start)
            rows = list(rows)
            if not rows:
                continue

            before = sum(r.outstanding for r in rows)
            changed = []
            carry = 0.0
            previous = None

            with transaction.atomic():
                for row in rows:
                    old_bf = row.brought_forward or 0.0
                    old_carried = row.carried_forward or 0.0
                    if abs(old_bf - carry) > 0.005:
                        row.brought_forward = carry
                    # recalc without committing on a dry run: we only want the
                    # recomputed figures for the report.
                    row.recalc(commit=not dry, propagate=False)
                    if previous is not None:
                        if dry:
                            previous.carried_forward = carry
                        else:
                            previous._stamp_carried(carry)
                    if (abs(old_bf - (row.brought_forward or 0.0)) > 0.005
                            or abs(old_carried - (row.carried_forward or 0.0)) > 0.005):
                        changed.append((row, old_bf))
                    previous, carry = row, row.balance_due

                if previous is not None:
                    if dry:
                        previous.carried_forward = 0.0
                    else:
                        previous._stamp_carried(0.0)

                if dry:
                    transaction.set_rollback(True)

            after = sum(r.outstanding for r in rows)
            grand_before += before
            grand_after += after
            total_changed += len(changed)

            self.stdout.write(
                f"\n  {branch.name}: {len(rows)} row(s), {len(changed)} corrected"
            )
            self.stdout.write(
                f"    outstanding {before:,.2f} -> {after:,.2f}   "
                f"closing balance {carry:,.2f}"
            )
            for row, old_bf in changed[:10]:
                self.stdout.write(
                    f"      {row.date}  brought forward {old_bf:,.2f} -> "
                    f"{row.brought_forward or 0.0:,.2f}"
                )
            if len(changed) > 10:
                self.stdout.write(f"      … and {len(changed) - 10} more")

        self.stdout.write(self.style.MIGRATE_HEADING("\n  Totals"))
        self.stdout.write(f"    rows corrected : {total_changed}")
        self.stdout.write(
            f"    outstanding    : {grand_before:,.2f} -> {grand_after:,.2f}"
        )
        if dry:
            self.stdout.write(self.style.WARNING(
                "\n  Dry run — nothing was written.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\n  Chain rebuilt.\n"))
