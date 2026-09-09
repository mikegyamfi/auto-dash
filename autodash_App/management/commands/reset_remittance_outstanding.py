"""Clear the remittance backlog so outstanding starts from zero.

`DailyRemittance` carries any unremitted balance into the next day via
`brought_forward`, so a stretch of unrecorded days snowballs into an outstanding
figure that reflects history rather than anything owed now.

This writes that backlog off:

  * `brought_forward` is zeroed on every row in scope, so nothing is pulled in
    from the past.
  * on rows that were left unpaid, `target_amount` is lowered to what was
    actually remitted, so `total_due == amount_remitted` and `outstanding`
    becomes 0. Without this the middleware would just carry the same shortfall
    into tomorrow again.

Recorded payments are never touched, so what was actually handed over stays on
the record. What is lost is the memory of what was *expected* on written-off
days — that is the point of a reset, but it is not reversible, so run
`--dry-run` first.

Usage:
    python manage.py reset_remittance_outstanding --dry-run
    python manage.py reset_remittance_outstanding
    python manage.py reset_remittance_outstanding --branch 2
    python manage.py reset_remittance_outstanding --before 2026-09-01
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autodash_App.models import Branch, DailyRemittance


class Command(BaseCommand):
    help = "Zero the carried-forward remittance backlog so outstanding starts at 0."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")
        parser.add_argument("--branch", type=int,
                            help="Restrict to one branch id (default: every branch).")
        parser.add_argument("--before", metavar="YYYY-MM-DD",
                            help="Only rows before this date. Default: every row, "
                                 "including today's.")
        parser.add_argument("--keep-today-target", action="store_true",
                            help="Leave today's target intact and only clear what "
                                 "was carried into it.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        today = timezone.localdate()

        rows = DailyRemittance.objects.select_related("branch").order_by("branch__name", "date")
        if opts.get("branch"):
            branch = Branch.objects.filter(id=opts["branch"]).first()
            if branch is None:
                raise CommandError(f"No branch with id {opts['branch']}.")
            rows = rows.filter(branch=branch)
        if opts.get("before"):
            try:
                cutoff = datetime.strptime(opts["before"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--before must be YYYY-MM-DD.")
            rows = rows.filter(date__lt=cutoff)

        rows = list(rows)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nRemittance reset{'  (dry run)' if dry else ''} — {len(rows)} row(s)"
        ))

        if not rows:
            self.stdout.write("  Nothing to do.\n")
            return

        carried_cleared = 0.0
        written_off = 0.0
        touched = []

        for row in rows:
            keep_target = opts["keep_today_target"] and row.date == today

            new_brought_forward = 0.0
            new_target = row.target_amount or 0.0
            if not keep_target and (row.amount_remitted or 0.0) < (row.total_due or 0.0):
                # Lower the expectation to what was actually handed over, so the
                # day closes settled and carries nothing.
                new_target = row.amount_remitted or 0.0

            bf_delta = row.brought_forward or 0.0
            target_delta = (row.target_amount or 0.0) - new_target
            if abs(bf_delta) < 0.005 and abs(target_delta) < 0.005:
                continue

            carried_cleared += bf_delta
            written_off += target_delta
            touched.append({
                "row": row,
                "old_target": row.target_amount or 0.0,
                "new_target": new_target,
                "old_outstanding": row.outstanding,
            })

            if not dry:
                row.brought_forward = new_brought_forward
                row.target_amount = new_target
                row.save()
                row.recalc()

        self.stdout.write("\n  Rows changed          : %d" % len(touched))
        self.stdout.write("  Carried-forward cleared: %s" % f"{carried_cleared:,.2f}")
        self.stdout.write("  Targets written off    : %s" % f"{written_off:,.2f}")

        if touched:
            self.stdout.write("\n  Sample (up to 10):")
            for item in touched[:10]:
                row = item["row"]
                self.stdout.write(
                    "    %-14s %s  outstanding %9.2f -> 0.00   target %9.2f -> %9.2f"
                    % (row.branch.name[:14], row.date, item["old_outstanding"],
                       item["old_target"], item["new_target"])
                )

        if dry:
            self.stdout.write("\n  (dry run — nothing written)\n")
            return

        # Anything still carrying a balance would seed the snowball again.
        with transaction.atomic():
            leftover = [r for r in DailyRemittance.objects.all() if r.outstanding > 0.005]
        self.stdout.write(self.style.SUCCESS(
            f"\n  Done. Rows still showing an outstanding balance: {len(leftover)}"
        ))
        if leftover:
            self.stdout.write(
                "  (Those are days with a live target and no payment yet — "
                "expected if you left today's target in place.)"
            )
        self.stdout.write("")
