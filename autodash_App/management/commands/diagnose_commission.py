"""Explain why commission for a period doesn't match the configured rates.

Read-only. Reconciles the Commission rows in a window against what the current
`Service.commission_rate` / `OtherService.commission_rate` settings would
produce, and attributes the gap to the usual causes:

  * rate changed since the job was logged (Commission rows are snapshots and
    are never recomputed when a Service's rate is edited)
  * on-credit work, which earns commission but books no Revenue until paid
  * commission re-dated by a later edit, so it lands outside its job's period
  * a worker whose branch differs from the branch the job was logged at
  * legacy rows written before the current rounding rules

Usage:
    python manage.py diagnose_commission                     # last 30 days
    python manage.py diagnose_commission --days 7
    python manage.py diagnose_commission --start 2026-08-01 --end 2026-08-31
    python manage.py diagnose_commission --branch 2
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from autodash_App.models import (
    Commission, OtherService, Revenue, ServiceRendered, ServiceRenderedOrder,
)


def _money(x):
    return f"{x or 0:,.2f}"


class Command(BaseCommand):
    help = "Reconcile commission against configured rates for a period, and explain the gap."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30,
                            help="Window size ending today (default 30). Ignored if --start given.")
        parser.add_argument("--start", help="Start date, YYYY-MM-DD.")
        parser.add_argument("--end", help="End date, YYYY-MM-DD (defaults to today).")
        parser.add_argument("--branch", type=int, help="Restrict to one branch id.")

    def handle(self, *args, **opts):
        today = timezone.localdate()
        if opts.get("start"):
            start = timezone.datetime.strptime(opts["start"], "%Y-%m-%d").date()
            end = (timezone.datetime.strptime(opts["end"], "%Y-%m-%d").date()
                   if opts.get("end") else today)
        else:
            end = today
            start = end - timedelta(days=opts["days"] - 1)

        branch_id = opts.get("branch")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nCommission diagnosis: {start} .. {end}"
            + (f"  (branch {branch_id})" if branch_id else "  (all branches)")
        ))

        comm = Commission.objects.filter(date__range=[start, end])
        rev = Revenue.objects.filter(date__range=[start, end])
        if branch_id:
            comm = comm.filter(worker__branch_id=branch_id)
            rev = rev.filter(branch_id=branch_id)

        comm_total = comm.aggregate(t=Sum("amount"))["t"] or 0.0
        rev_total = rev.aggregate(t=Sum("final_amount"))["t"] or 0.0

        self.stdout.write("\n  Headline")
        self.stdout.write(f"    Revenue (Revenue.final_amount)  : {_money(rev_total)}")
        self.stdout.write(f"    Commission (Commission.amount)  : {_money(comm_total)}")
        if rev_total:
            self.stdout.write(
                f"    Commission as % of revenue      : {comm_total / rev_total * 100:.2f}%"
            )

        self._per_service(comm)
        self._on_credit(start, end, branch_id)
        self._redated(comm)
        self._cross_branch(comm)
        self._legacy_rows(comm)

        self.stdout.write("")

    # ------------------------------------------------------------------
    def _per_service(self, comm):
        """Configured rate vs the rate actually paid, per service."""
        self.stdout.write("\n  Rate actually paid vs rate configured now")
        self.stdout.write(
            f"    {'Service':<28}{'now':>7}{'paid':>9}{'lines':>7}{'value':>12}{'commission':>13}"
        )

        buckets = {}
        for c in comm.select_related("service_rendered__service"):
            sr = c.service_rendered
            if sr is None or sr.service_id is None:
                continue
            key = (sr.service.service_type, sr.service.price, sr.service.commission_rate)
            b = buckets.setdefault(key, {"commission": 0.0, "lines": set()})
            b["commission"] += c.amount or 0.0
            b["lines"].add(sr.id)

        flagged = []
        for (name, price, rate), b in sorted(buckets.items()):
            value = sum(
                sr.get_effective_price()
                for sr in ServiceRendered.objects.filter(id__in=b["lines"]).select_related("service")
            )
            paid = (b["commission"] / value * 100) if value else 0.0
            marker = ""
            # A rate that drifted by more than a rounding wobble means the
            # service's rate was edited after these jobs were logged.
            if rate and abs(paid - rate) > 0.5:
                marker = "  <-- rate changed since these jobs"
                flagged.append((name, rate, paid, b["commission"]))
            self.stdout.write(
                f"    {name[:27]:<28}{rate:>6.2f}%{paid:>8.2f}%{len(b['lines']):>7}"
                f"{value:>12,.2f}{b['commission']:>13,.2f}{marker}"
            )

        other = comm.filter(other_service__isnull=False)
        if other.exists():
            self.stdout.write(
                f"    {'(other services)':<28}{'-':>7}{'-':>9}"
                f"{other.values('other_service').distinct().count():>7}"
                f"{'-':>12}{other.aggregate(t=Sum('amount'))['t'] or 0:>13,.2f}"
            )

        if flagged:
            self.stdout.write(self.style.WARNING(
                "\n    ^ Commission rows are snapshots taken when the job was logged."
                "\n      Editing Service.commission_rate does NOT recompute them, so old"
                "\n      jobs keep paying the old rate. This is the usual cause of a"
                "\n      commission total that looks far too big for the current rate."
            ))

    # ------------------------------------------------------------------
    def _on_credit(self, start, end, branch_id):
        """Commission earned on work that has not produced Revenue yet."""
        orders = ServiceRenderedOrder.objects.filter(
            status="onCredit", date__date__range=[start, end]
        )
        others = OtherService.objects.filter(
            status="onCredit", created_at__date__range=[start, end]
        )
        if branch_id:
            orders = orders.filter(branch_id=branch_id)
            others = others.filter(branch_id=branch_id)

        comm_on_credit = Commission.objects.filter(
            service_rendered__order__in=orders
        ).aggregate(t=Sum("amount"))["t"] or 0.0
        comm_on_credit += Commission.objects.filter(
            other_service__in=others
        ).aggregate(t=Sum("amount"))["t"] or 0.0

        owed = (orders.aggregate(t=Sum("final_amount"))["t"] or 0.0) + \
               (others.aggregate(t=Sum("amount"))["t"] or 0.0)

        self.stdout.write("\n  On-credit work (earns commission, books no revenue until paid)")
        self.stdout.write(f"    Orders/jobs on credit           : {orders.count() + others.count()}")
        self.stdout.write(f"    Value owed                      : {_money(owed)}")
        self.stdout.write(f"    Commission already paid on it   : {_money(comm_on_credit)}")

    # ------------------------------------------------------------------
    def _redated(self, comm):
        """Rows whose date no longer matches the job they belong to."""
        moved, checked, amount = 0, 0, 0.0
        for c in comm.select_related("service_rendered__order", "other_service"):
            job_date = None
            if c.service_rendered_id and c.service_rendered.order_id:
                job_date = c.service_rendered.order.date.date()
            elif c.other_service_id:
                job_date = c.other_service.created_at.date()
            if job_date is None:
                continue
            checked += 1
            if c.date != job_date:
                moved += 1
                amount += c.amount or 0.0

        self.stdout.write("\n  Commission re-dated by a later edit")
        self.stdout.write(f"    Rows dated away from their job  : {moved} of {checked}")
        self.stdout.write(f"    Amount involved                 : {_money(amount)}")
        if moved:
            self.stdout.write(self.style.WARNING(
                "    Re-allocating an old job stamps its commission with today's date,"
                "\n      so it lands in this period while its revenue stays in the original one."
            ))

    # ------------------------------------------------------------------
    def _cross_branch(self, comm):
        """Commission counted against a different branch than the job."""
        rows, amount = 0, 0.0
        for c in comm.select_related("worker", "service_rendered__order", "other_service"):
            job_branch = None
            if c.service_rendered_id and c.service_rendered.order_id:
                job_branch = c.service_rendered.order.branch_id
            elif c.other_service_id:
                job_branch = c.other_service.branch_id
            if job_branch and c.worker.branch_id != job_branch:
                rows += 1
                amount += c.amount or 0.0

        self.stdout.write("\n  Worker branch != job branch")
        self.stdout.write(f"    Rows                            : {rows}")
        self.stdout.write(f"    Amount                          : {_money(amount)}")
        if rows:
            self.stdout.write(self.style.WARNING(
                "    Reports scope revenue by job branch but commission by worker branch,"
                "\n      so these land on different branches' books."
            ))

    # ------------------------------------------------------------------
    def _legacy_rows(self, comm):
        """Amounts that the current 2dp splitter would never have written."""
        odd = [c for c in comm if c.amount is not None and round(c.amount, 2) != c.amount]
        self.stdout.write("\n  Legacy rows (more than 2 decimal places)")
        self.stdout.write(f"    Rows                            : {len(odd)}")
        self.stdout.write(f"    Amount                          : {_money(sum(c.amount for c in odd))}")
