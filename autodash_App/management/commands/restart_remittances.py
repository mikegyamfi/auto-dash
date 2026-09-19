"""
Start remittance over from zero.

Two ways to do it, because they lose different things:

  * default — **deletes** every `DailyRemittance`, and with it (by cascade)
    every `RemittancePayment`. Nothing is left: no targets, no arrears, no
    record of what was ever handed over. The next request opens today's row
    fresh at `brought_forward` 0 from each branch's `RemittanceSetup`.

  * `--keep-payments` — keeps the rows and every payment ever recorded, but
    zeroes the carry chain and writes unpaid targets down to what was actually
    remitted, so nothing is outstanding anywhere and nothing carries into
    tomorrow. History stays readable; only the debt goes.

Deleting is refused unless you pass `--yes`, because the payment record is the
only evidence of what each branch handed over.

    python manage.py restart_remittances --dry-run
    python manage.py restart_remittances --yes
    python manage.py restart_remittances --keep-payments --yes
    python manage.py restart_remittances --branch 3 --yes

`RemittanceSetup` is never touched either way — targets and operating days stay
configured, so remittance simply begins again from today.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autodash_App.models import (
    Branch, DailyRemittance, RemittancePayment, RemittanceSetup,
)


class Command(BaseCommand):
    help = "Clear remittance history so every branch starts again from zero."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually do it. Without this the command only reports.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change and write nothing (same as omitting --yes).",
        )
        parser.add_argument(
            "--branch", type=int, default=None,
            help="Limit to one branch id (default: every branch).",
        )
        parser.add_argument(
            "--keep-payments", action="store_true",
            help="Keep the rows and payment history; just zero the balances.",
        )

    def handle(self, *args, **opts):
        write = opts["yes"] and not opts["dry_run"]
        keep = opts["keep_payments"]

        rows = DailyRemittance.objects.select_related("branch")
        if opts["branch"]:
            branch = Branch.objects.filter(id=opts["branch"]).first()
            if branch is None:
                raise CommandError(f"No branch with id {opts['branch']}.")
            rows = rows.filter(branch=branch)

        rows = list(rows.order_by("branch__name", "date"))
        if not rows:
            self.stdout.write(self.style.SUCCESS(
                "\nNo remittance rows - already starting from zero.\n"
            ))
            return

        payments = RemittancePayment.objects.filter(
            remittance__in=[r.pk for r in rows]
        )
        payment_count = payments.count()
        payment_total = sum(p.amount or 0.0 for p in payments)
        outstanding = sum(r.outstanding for r in rows)

        mode = "zero the balances, keep history" if keep else "DELETE everything"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nRestart remittances - {mode}"
        ))
        self.stdout.write(f"  Rows in scope        : {len(rows)}")
        self.stdout.write(f"  Payments in scope    : {payment_count} "
                          f"(GHS {payment_total:,.2f} recorded)")
        self.stdout.write(f"  Outstanding now      : GHS {outstanding:,.2f}")

        per_branch = {}
        for row in rows:
            entry = per_branch.setdefault(row.branch.name, [0, 0.0])
            entry[0] += 1
            entry[1] += row.outstanding
        self.stdout.write("\n  By branch:")
        for name, (count, owed) in sorted(per_branch.items()):
            self.stdout.write(f"    {name:<20} {count:>4} row(s)   outstanding {owed:>12,.2f}")

        if not write:
            self.stdout.write(self.style.WARNING(
                "\n  Nothing written. Re-run with --yes to apply."
            ))
            if not keep:
                self.stdout.write(
                    "  Note: without --keep-payments this deletes the record of "
                    f"GHS {payment_total:,.2f} actually remitted.\n"
                )
            return

        with transaction.atomic():
            if keep:
                for row in rows:
                    row.brought_forward = 0.0
                    row.carried_forward = 0.0
                    # Expect only what was really handed over, so the day closes
                    # settled and carries nothing.
                    if (row.amount_remitted or 0.0) < (row.target_amount or 0.0):
                        row.target_amount = row.amount_remitted or 0.0
                    row.save()
                    row.recalc()
                removed = 0
            else:
                removed, _ = DailyRemittance.objects.filter(
                    pk__in=[r.pk for r in rows]
                ).delete()

        if keep:
            left = sum(
                r.outstanding for r in DailyRemittance.objects.filter(
                    pk__in=[r.pk for r in rows]
                )
            )
            self.stdout.write(self.style.SUCCESS(
                f"\n  Balances zeroed on {len(rows)} row(s). "
                f"Payments untouched. Outstanding now: GHS {left:,.2f}\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n  Deleted {removed} object(s) - every remittance row and payment "
                f"in scope is gone.\n"
            ))

        active = RemittanceSetup.objects.filter(is_active=True).count()
        self.stdout.write(
            f"  {active} active remittance setup(s) kept. Today's row reopens on "
            f"the next request, at brought forward 0.\n"
        )
