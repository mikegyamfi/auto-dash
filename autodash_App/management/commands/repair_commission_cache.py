"""Repair the denormalised `commission_amount` cache.

The cache is meant to equal the sum of the Commission rows behind a job. Two
older behaviours broke that:

  * `ServiceRendered.save()` used to guess a commission at creation time, before
    any workers were attached, leaving lines that claim money with no Commission
    rows behind them ("phantom" commission).
  * the split rounded each share independently, so three shares of a GHS 10 pool
    summed to 9.99 while the cache said 10.00.

This command recomputes each cache from the rows that actually exist. It does
NOT change any Commission amount, so nobody's payout is restated.

`--fix-dates` additionally re-dates commissions onto their job's date. That one
DOES move figures between reporting periods, so it is opt-in.

Usage:
    python manage.py repair_commission_cache --dry-run
    python manage.py repair_commission_cache
    python manage.py repair_commission_cache --fix-dates
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from autodash_App.commission_util import _service_rendered_date
from autodash_App.models import Commission, OtherService, ServiceRendered


class Command(BaseCommand):
    help = "Recompute commission_amount caches from the Commission rows that actually exist."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")
        parser.add_argument("--fix-dates", action="store_true",
                            help="Also re-date commissions onto their job's date "
                                 "(moves figures between reporting periods).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nCommission cache repair" + ("  (dry run)" if dry else "")
        ))

        phantom, drifted, cache_delta, overstated = self._scan_caches()

        self.stdout.write("\n  Caches claiming money with no Commission rows behind them")
        self.stdout.write(f"    Jobs      : {len(phantom)}")
        self.stdout.write(f"    Overstated: {overstated:,.2f}")

        self.stdout.write("\n  Caches that disagree with the sum of their rows")
        self.stdout.write(f"    Jobs      : {len(drifted)}")
        self.stdout.write(f"    Net drift : {cache_delta:,.2f}")

        if not dry:
            with transaction.atomic():
                fixed = self._apply(phantom + drifted)
            self.stdout.write(self.style.SUCCESS(f"\n  Rewrote {fixed} cached totals."))
        else:
            self.stdout.write("\n  (dry run — nothing written)")

        if opts["fix_dates"]:
            self._fix_dates(dry)

        self.stdout.write("")

    # ------------------------------------------------------------------
    def _scan_caches(self):
        """Split jobs into phantom-cache and drifted-cache, with the true total."""
        phantom, drifted, delta, overstated = [], [], 0.0, 0.0

        for model, related in ((ServiceRendered, "commissions"), (OtherService, "commissions")):
            for job in model.objects.prefetch_related(related).iterator(chunk_size=500):
                cached = job.commission_amount or 0.0
                actual = sum(c.amount or 0.0 for c in getattr(job, related).all())
                if abs(cached - actual) <= 0.005:
                    continue
                if actual == 0.0:
                    # Nothing backs this cache at all; it should read zero.
                    phantom.append((job, 0.0))
                    overstated += cached
                else:
                    drifted.append((job, actual))
                    delta += cached - actual

        return phantom, drifted, delta, overstated

    def _apply(self, entries):
        count = 0
        for job, actual in entries:
            type(job).objects.filter(pk=job.pk).update(commission_amount=actual)
            count += 1
        return count

    # ------------------------------------------------------------------
    def _fix_dates(self, dry):
        moved = []
        for c in Commission.objects.select_related(
            "service_rendered__order", "other_service"
        ).iterator(chunk_size=500):
            if c.service_rendered_id:
                job_date = _service_rendered_date(c.service_rendered)
            elif c.other_service_id:
                job_date = c.other_service.created_at.date() if c.other_service.created_at else None
            else:
                continue
            if job_date and c.date != job_date:
                moved.append((c.pk, job_date))

        self.stdout.write("\n  Commissions dated away from their job")
        self.stdout.write(f"    Rows      : {len(moved)}")
        if not dry and moved:
            with transaction.atomic():
                for pk, job_date in moved:
                    Commission.objects.filter(pk=pk).update(date=job_date)
            self.stdout.write(self.style.SUCCESS(f"    Re-dated {len(moved)} rows onto their job's date."))
        elif moved:
            self.stdout.write("    (dry run — nothing written)")
