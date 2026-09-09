from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autodash_App.models import (
    Branch, CustomUser, DailyRemittance, RemittancePayment, RemittanceSetup,
    Worker, WorkerCategory,
)


class ResetRemittanceOutstandingTest(TestCase):
    """
    The backlog snowballs through `brought_forward`. The reset writes it off so
    outstanding starts at zero and nothing is pulled in from the past.
    """

    def setUp(self):
        self.ridge = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.teshie = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        self.today = timezone.localdate()

        # Three unpaid days that have compounded into a large outstanding.
        self.rows = []
        carried = 0.0
        for offset in (3, 2, 1):
            row = DailyRemittance.objects.create(
                branch=self.ridge, date=self.today - timedelta(days=offset),
                target_amount=500.0, brought_forward=carried,
            )
            carried = row.carry_to_next_day()
            self.rows.append(row)

        self.other = DailyRemittance.objects.create(
            branch=self.teshie, date=self.today - timedelta(days=1),
            target_amount=300.0, brought_forward=900.0,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("reset_remittance_outstanding", *args, stdout=out)
        return out.getvalue()

    def test_the_backlog_compounds_before_the_reset(self):
        last = self.rows[-1]
        self.assertAlmostEqual(last.brought_forward, 1000.0)
        self.assertAlmostEqual(last.outstanding, 1500.0)

    def test_dry_run_changes_nothing(self):
        output = self._run("--dry-run")
        self.assertIn("dry run", output)

        self.rows[-1].refresh_from_db()
        self.assertAlmostEqual(self.rows[-1].outstanding, 1500.0)

    def test_it_zeroes_every_outstanding_balance(self):
        self._run()
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.outstanding, 0.0, msg=str(row))

    def test_it_clears_what_was_carried_from_the_past(self):
        self._run()
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.brought_forward, 0.0)

    def test_nothing_carries_into_the_next_day(self):
        """The point of the reset: tomorrow starts clean."""
        self._run()
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_recorded_payments_are_never_touched(self):
        row = self.rows[0]
        RemittancePayment.objects.create(
            remittance=row, source="cash", amount=200.0
        )
        row.refresh_from_db()

        self._run()

        row.refresh_from_db()
        self.assertAlmostEqual(row.amount_remitted, 200.0)
        self.assertEqual(row.payments.count(), 1)
        # The target drops to what was actually handed over, so it closes settled.
        self.assertAlmostEqual(row.target_amount, 200.0)
        self.assertAlmostEqual(row.outstanding, 0.0)

    def test_it_can_be_limited_to_one_branch(self):
        self._run("--branch", str(self.ridge.id))

        self.assertAlmostEqual(
            DailyRemittance.objects.get(branch=self.teshie).outstanding, 1200.0
        )
        for row in DailyRemittance.objects.filter(branch=self.ridge):
            self.assertAlmostEqual(row.outstanding, 0.0)

    def test_it_can_keep_todays_target(self):
        DailyRemittance.objects.create(
            branch=self.ridge, date=self.today,
            target_amount=500.0, brought_forward=1500.0,
        )
        self._run("--keep-today-target")

        todays = DailyRemittance.objects.get(branch=self.ridge, date=self.today)
        self.assertAlmostEqual(todays.brought_forward, 0.0)   # no pull from the past
        self.assertAlmostEqual(todays.target_amount, 500.0)   # today still expected
        self.assertAlmostEqual(todays.outstanding, 500.0)

    def test_it_can_be_limited_by_date(self):
        cutoff = self.today - timedelta(days=1)
        self._run("--before", cutoff.strftime("%Y-%m-%d"))

        untouched = DailyRemittance.objects.get(branch=self.ridge, date=cutoff)
        self.assertAlmostEqual(untouched.brought_forward, 1000.0)


class RemittanceReportScopeTest(TestCase):
    """Unfiltered the report covers every branch; a filter narrows it."""

    def setUp(self):
        self.ridge = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.teshie = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        today = timezone.localdate()
        DailyRemittance.objects.create(
            branch=self.ridge, date=today, target_amount=500.0
        )
        DailyRemittance.objects.create(
            branch=self.teshie, date=today, target_amount=300.0
        )
        self.client.force_login(self.staff)

    def _get(self, **params):
        return self.client.get(reverse("remittance_report"), params)

    def test_unfiltered_covers_every_branch(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["show_all"])
        self.assertEqual(len(r.context["rows"]), 2)
        self.assertAlmostEqual(r.context["totals"]["due"], 800.0)

    def test_unfiltered_breaks_the_total_down_by_branch(self):
        rows = {b["branch"].name: b for b in self._get().context["by_branch"]}
        self.assertAlmostEqual(rows["Ridge"]["due"], 500.0)
        self.assertAlmostEqual(rows["Teshie"]["due"], 300.0)

    def test_the_table_names_the_branch_when_unfiltered(self):
        r = self._get()
        self.assertContains(r, "Ridge")
        self.assertContains(r, "Teshie")
        self.assertContains(r, "All branches")

    def test_filtering_narrows_to_one_branch(self):
        r = self._get(branch_id=self.ridge.id)
        self.assertFalse(r.context["show_all"])
        self.assertEqual(len(r.context["rows"]), 1)
        self.assertAlmostEqual(r.context["totals"]["due"], 500.0)

    def test_a_worker_is_pinned_to_their_own_branch(self):
        category = WorkerCategory.objects.create(name="Washer", service_provider=True)
        user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="worker", approved=True
        )
        Worker.objects.create(
            user=user, branch=self.teshie, worker_category=category,
            is_branch_admin=True,
        )
        self.client.force_login(user)

        r = self.client.get(reverse("remittance_report"), {"branch_id": self.ridge.id})
        self.assertEqual(r.context["branch"], self.teshie)
        self.assertEqual(len(r.context["rows"]), 1)
