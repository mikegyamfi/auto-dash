"""
Starting remittance over. Deleting the payment record is the destructive half,
so the default must refuse without --yes, and --keep-payments must really keep
them.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from autodash_App.models import (
    Branch, DailyRemittance, RemittancePayment, RemittanceSetup,
)


class RestartRemittancesTest(TestCase):

    def setUp(self):
        self.ridge = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.teshie = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        RemittanceSetup.objects.create(branch=self.ridge, target_amount=1200.0)
        RemittanceSetup.objects.create(branch=self.teshie, target_amount=800.0)
        today = timezone.localdate()

        carried = 0.0
        for offset in (3, 2, 1):
            row = DailyRemittance.objects.create(
                branch=self.ridge, date=today - timedelta(days=offset),
                target_amount=1200.0, brought_forward=carried,
            )
            row.recalc()
            carried = row.carry_to_next_day()
        self.paid_row = DailyRemittance.objects.filter(branch=self.ridge).first()
        RemittancePayment.objects.create(
            remittance=self.paid_row, source="cash", amount=500.0
        )
        DailyRemittance.objects.create(
            branch=self.teshie, date=today - timedelta(days=1),
            target_amount=800.0, brought_forward=1600.0,
        ).recalc()

    def _run(self, *args):
        out = StringIO()
        call_command("restart_remittances", *args, stdout=out)
        return out.getvalue()

    # ---- the safety catch ----------------------------------------------
    def test_without_yes_it_only_reports(self):
        before = DailyRemittance.objects.count()
        output = self._run()
        self.assertEqual(DailyRemittance.objects.count(), before)
        self.assertEqual(RemittancePayment.objects.count(), 1)
        self.assertIn("Nothing written", output)

    def test_dry_run_overrides_yes(self):
        self._run("--yes", "--dry-run")
        self.assertTrue(DailyRemittance.objects.exists())

    def test_it_warns_that_the_payment_record_goes(self):
        self.assertIn("actually remitted", self._run())

    # ---- the full wipe --------------------------------------------------
    def test_yes_deletes_every_row_and_payment(self):
        self._run("--yes")
        self.assertEqual(DailyRemittance.objects.count(), 0)
        self.assertEqual(RemittancePayment.objects.count(), 0)

    def test_the_setups_survive_so_it_can_start_again(self):
        self._run("--yes")
        self.assertEqual(RemittanceSetup.objects.count(), 2)
        self.assertAlmostEqual(
            RemittanceSetup.objects.get(branch=self.ridge).target_amount, 1200.0
        )

    def test_it_can_be_limited_to_one_branch(self):
        self._run("--branch", str(self.ridge.id), "--yes")
        self.assertFalse(DailyRemittance.objects.filter(branch=self.ridge).exists())
        self.assertTrue(DailyRemittance.objects.filter(branch=self.teshie).exists())

    # ---- the non-destructive half ---------------------------------------
    def test_keep_payments_leaves_every_payment_in_place(self):
        self._run("--keep-payments", "--yes")
        self.assertEqual(RemittancePayment.objects.count(), 1)
        self.assertEqual(DailyRemittance.objects.count(), 4)

    def test_keep_payments_leaves_nothing_outstanding(self):
        self._run("--keep-payments", "--yes")
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.outstanding, 0.0, msg=f"{row.date} still owes")
            self.assertAlmostEqual(row.brought_forward, 0.0)
            self.assertTrue(row.is_settled)

    def test_keep_payments_carries_nothing_into_tomorrow(self):
        self._run("--keep-payments", "--yes")
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_keep_payments_expects_only_what_was_handed_over(self):
        self._run("--keep-payments", "--yes")
        self.paid_row.refresh_from_db()
        self.assertAlmostEqual(self.paid_row.amount_remitted, 500.0)
        self.assertAlmostEqual(self.paid_row.target_amount, 500.0)

    def test_it_is_a_no_op_when_there_is_nothing_to_clear(self):
        self._run("--yes")
        self.assertIn("already starting from zero", self._run("--yes"))


class FreshStartTodayTest(TestCase):
    """
    After a wipe, today must open clean: no arrears, no target inherited from a
    day that no longer exists. This is the whole point of the command.
    """

    def setUp(self):
        from autodash_App.models import CustomUser
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        RemittanceSetup.objects.create(branch=self.branch, target_amount=1200.0)
        self.today = timezone.localdate()

        # A month of unpaid history, compounding into a large backlog.
        carried = 0.0
        for offset in range(30, 0, -1):
            row = DailyRemittance.objects.create(
                branch=self.branch, date=self.today - timedelta(days=offset),
                target_amount=1200.0, brought_forward=carried,
            )
            row.recalc()
            carried = row.carry_to_next_day()
        DailyRemittance.objects.create(
            branch=self.branch, date=self.today,
            target_amount=1200.0, brought_forward=carried,
        ).recalc()

        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.client.force_login(self.staff)

    def test_the_backlog_is_real_before_the_wipe(self):
        today = DailyRemittance.objects.get(date=self.today)
        self.assertAlmostEqual(today.brought_forward, 36000.0)

    def test_after_the_wipe_today_reopens_pulling_nothing(self):
        call_command("restart_remittances", "--yes", stdout=StringIO())
        self.assertEqual(DailyRemittance.objects.count(), 0)

        # Opening the page is what reopens today's row.
        from django.urls import reverse
        self.client.get(reverse("remittance_list"), {"branch_id": self.branch.id})

        rows = DailyRemittance.objects.all()
        self.assertEqual(rows.count(), 1)
        today = rows.first()
        self.assertEqual(today.date, self.today)
        self.assertAlmostEqual(today.brought_forward, 0.0)
        self.assertAlmostEqual(today.target_amount, 1200.0)
        self.assertAlmostEqual(today.total_due, 1200.0)
        self.assertAlmostEqual(today.outstanding, 1200.0)

    def test_remitting_todays_target_then_settles_and_carries_nothing(self):
        call_command("restart_remittances", "--yes", stdout=StringIO())
        from django.urls import reverse
        self.client.get(reverse("remittance_list"), {"branch_id": self.branch.id})
        today = DailyRemittance.objects.get(date=self.today)

        RemittancePayment.objects.create(
            remittance=today, source="cash", amount=1200.0
        )
        today.refresh_from_db()
        self.assertTrue(today.is_settled)
        self.assertAlmostEqual(today.outstanding, 0.0)
        self.assertAlmostEqual(today.carry_to_next_day(), 0.0)
