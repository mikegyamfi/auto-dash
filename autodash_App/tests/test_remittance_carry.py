"""
The remittance carry chain.

The rules, as the business states them:

  * every operating day you owe `target + brought_forward`
  * whatever you don't hand over carries to tomorrow
  * brought forward is arrears — it never goes negative, so over-remitting
    buys no credit
  * a day with no row owed nothing

These pin that arithmetic and, just as importantly, that a day's balance is
owed in exactly ONE place: once a later day takes it on, the day it came from
stops reporting it. Without that, totalling a range counts the same cedi once
per day it stayed unpaid, and history shows red for money already settled.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autodash_App.models import (
    Branch, CustomUser, DailyRemittance, RemittancePayment, RemittanceSetup,
)


class CarryForwardChainTest(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        RemittanceSetup.objects.create(branch=self.branch, target_amount=1200.0)
        self.today = timezone.localdate()

    def _open(self, days_ago, brought_forward=0.0, net_sales=0.0, target=1200.0):
        row = DailyRemittance.objects.create(
            branch=self.branch, date=self.today - timedelta(days=days_ago),
            target_amount=target, brought_forward=brought_forward,
            net_sales=net_sales, is_finalized=True,
        )
        row.recalc()
        return row

    def _remit(self, row, amount):
        RemittancePayment.objects.create(remittance=row, source="cash", amount=amount)
        row.refresh_from_db()
        return row

    # ---- the acceptance case -------------------------------------------
    def test_remitting_the_target_settles_the_day(self):
        """net 1500, target 1200, remit 1200 -> settled, nothing carries."""
        row = self._remit(self._open(1, net_sales=1500.0), 1200.0)
        self.assertAlmostEqual(row.total_due, 1200.0)
        self.assertAlmostEqual(row.amount_remitted, 1200.0)
        self.assertAlmostEqual(row.outstanding, 0.0)
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_tomorrow_opens_at_zero_after_the_target_is_remitted(self):
        yesterday = self._remit(self._open(1, net_sales=1500.0), 1200.0)
        today = self._open(0, brought_forward=yesterday.carry_to_next_day())
        self.assertAlmostEqual(today.brought_forward, 0.0)
        self.assertAlmostEqual(today.total_due, 1200.0)
        self.assertAlmostEqual(today.outstanding, 1200.0)

    def test_surplus_is_flagged_but_never_carried(self):
        row = self._remit(self._open(1, net_sales=1500.0), 1200.0)
        self.assertAlmostEqual(row.surplus, 300.0)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    # ---- shortfalls carry ----------------------------------------------
    def test_a_missed_target_carries_the_shortfall(self):
        """net 800 against a 1200 target: 400 follows into tomorrow."""
        yesterday = self._remit(self._open(1, net_sales=800.0), 800.0)
        self.assertAlmostEqual(yesterday.carry_to_next_day(), 400.0)
        today = self._open(0, brought_forward=yesterday.carry_to_next_day())
        self.assertAlmostEqual(today.brought_forward, 400.0)
        self.assertAlmostEqual(today.total_due, 1600.0)

    def test_a_dead_day_carries_the_whole_target(self):
        self.assertAlmostEqual(self._open(1, net_sales=0.0).carry_to_next_day(), 1200.0)

    def test_over_remitting_never_becomes_a_credit(self):
        row = self._remit(self._open(1, net_sales=1500.0), 1500.0)
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)  # not -300

    # ---- a balance is owed in exactly one place ------------------------
    def test_a_carried_day_stops_reporting_it_as_outstanding(self):
        yesterday = self._open(1)
        today = self._open(0, brought_forward=yesterday.carry_to_next_day())
        yesterday.propagate_forward()
        yesterday.refresh_from_db()
        self.assertTrue(yesterday.is_carried)
        self.assertAlmostEqual(yesterday.outstanding, 0.0)
        # Today owes its own target plus the balance it took on.
        self.assertAlmostEqual(today.outstanding, 2400.0)

    def test_a_three_day_backlog_totals_the_real_debt_not_the_sum(self):
        first = self._open(2)
        second = self._open(1, brought_forward=first.carry_to_next_day())
        self._open(0, brought_forward=second.carry_to_next_day())
        first.propagate_forward()
        rows = list(DailyRemittance.objects.order_by("date"))
        # Running balances are 1200 / 2400 / 3600. The debt is 3600, not 7200.
        self.assertAlmostEqual(rows[-1].total_due, 3600.0)
        self.assertAlmostEqual(sum(r.outstanding for r in rows), 3600.0)

    def test_paying_the_backlog_clears_every_row(self):
        first = self._open(2)
        second = self._open(1, brought_forward=first.carry_to_next_day())
        third = self._open(0, brought_forward=second.carry_to_next_day())
        first.propagate_forward()
        self._remit(third, 3600.0)
        for row in DailyRemittance.objects.order_by("date"):
            self.assertAlmostEqual(row.outstanding, 0.0, msg=f"{row.date} still owes")

    # ---- the chain repairs itself --------------------------------------
    def test_paying_an_old_day_rebuilds_every_later_day(self):
        first = self._open(2)
        second = self._open(1, brought_forward=first.carry_to_next_day())
        third = self._open(0, brought_forward=second.carry_to_next_day())
        first.propagate_forward()
        self.assertAlmostEqual(DailyRemittance.objects.get(pk=third.pk).total_due, 3600.0)

        self._remit(first, 1200.0)  # the missed day is settled after the fact

        second.refresh_from_db()
        third.refresh_from_db()
        self.assertAlmostEqual(second.brought_forward, 0.0)
        self.assertAlmostEqual(third.brought_forward, 1200.0)
        self.assertAlmostEqual(third.total_due, 2400.0)

    def test_deleting_a_payment_rebuilds_every_later_day(self):
        first = self._open(1)
        second = self._open(0, brought_forward=first.carry_to_next_day())
        first.propagate_forward()
        payment = RemittancePayment.objects.create(
            remittance=first, source="cash", amount=1200.0
        )
        second.refresh_from_db()
        self.assertAlmostEqual(second.brought_forward, 0.0)

        payment.delete()
        second.refresh_from_db()
        self.assertAlmostEqual(second.brought_forward, 1200.0)

    # ---- the prefill offers what is owed -------------------------------
    def test_prefill_offers_the_target_not_the_takings(self):
        row = self._open(0, net_sales=1500.0)
        self.assertEqual(
            [(r["label"], r["amount"]) for r in row.suggested_split()],
            [("Target", 1200.0)],
        )

    def test_prefill_covers_arrears_first(self):
        row = self._open(0, brought_forward=400.0, net_sales=2000.0)
        self.assertEqual(
            [(r["label"], r["amount"]) for r in row.suggested_split()],
            [("Brought forward", 400.0), ("Target", 1200.0)],
        )

    def test_prefill_can_actually_settle_a_row_with_arrears(self):
        row = self._open(0, brought_forward=400.0, net_sales=2000.0)
        for line in row.suggested_split():
            RemittancePayment.objects.create(
                remittance=row, source=line["source"], amount=line["amount"]
            )
        row.refresh_from_db()
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_prefill_is_capped_by_the_cash_actually_taken(self):
        row = self._open(0, brought_forward=400.0, net_sales=1000.0)
        lines = row.suggested_split()
        self.assertAlmostEqual(sum(r["amount"] for r in lines), 1000.0)
        self.assertEqual(lines[0]["label"], "Brought forward")

    def test_prefill_offers_nothing_when_no_cash_was_taken(self):
        self.assertEqual(self._open(0, net_sales=0.0).suggested_split(), [])

    def test_prefill_offers_nothing_once_settled(self):
        row = self._remit(self._open(0, net_sales=1500.0), 1200.0)
        self.assertEqual(row.suggested_split(), [])

    # ---- a hand-typed figure is accounted for, not silently carried ----
    def test_remitting_only_the_target_names_the_arrears_it_left(self):
        """
        The live complaint: managers remit 1200 every day and a stuck figure
        keeps showing. It is a part payment — this says so in figures.
        """
        row = self._remit(self._open(0, brought_forward=6000.0, net_sales=1500.0), 1200.0)
        split = row.allocation_for()
        self.assertAlmostEqual(split["arrears"], 1200.0)
        self.assertAlmostEqual(split["arrears_left"], 4800.0)
        self.assertAlmostEqual(split["target"], 0.0)
        self.assertAlmostEqual(row.balance_due, 6000.0)

    def test_allocation_reports_the_excess_once_everything_is_covered(self):
        row = self._remit(self._open(0, brought_forward=400.0, net_sales=3000.0), 2000.0)
        split = row.allocation_for()
        self.assertAlmostEqual(split["arrears"], 400.0)
        self.assertAlmostEqual(split["target"], 1200.0)
        self.assertAlmostEqual(split["excess"], 400.0)


class PastDatesAreReadOnlyTest(TestCase):
    """Looking at history must never invent a debt."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        RemittanceSetup.objects.create(branch=self.branch, target_amount=1200.0)
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.client.force_login(self.staff)

    def _view(self, day):
        return self.client.get(
            reverse("remittance_list"),
            {"date": day.strftime("%Y-%m-%d"), "branch_id": self.branch.id},
        )

    def test_viewing_a_past_date_creates_no_row(self):
        old = timezone.localdate() - timedelta(days=45)
        response = self._view(old)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["remittance"])
        self.assertFalse(DailyRemittance.objects.filter(date=old).exists())

    def test_browsing_history_invents_no_outstanding(self):
        today = timezone.localdate()
        for back in (45, 40, 30, 20, 10):
            self._view(today - timedelta(days=back))
        self.assertEqual(DailyRemittance.objects.exclude(date=today).count(), 0)

    def test_today_is_still_opened(self):
        response = self._view(timezone.localdate())
        self.assertIsNotNone(response.context["remittance"])
        self.assertAlmostEqual(response.context["remittance"].target_amount, 1200.0)


class RepairRemittanceChainTest(TestCase):
    """
    The chain was only ever written at row creation, so live data has rows whose
    brought_forward no longer follows from the day before. The repair rebuilds
    it without touching a target or a payment.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.today = timezone.localdate()
        # A deliberately broken chain: each day claims arrears nobody carried.
        self.rows = [
            DailyRemittance.objects.create(
                branch=self.branch, date=self.today - timedelta(days=offset),
                target_amount=1200.0, brought_forward=bogus, is_finalized=True,
            )
            for offset, bogus in ((3, 0.0), (2, 5000.0), (1, 9000.0))
        ]
        for row in self.rows:
            row.recalc()

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("repair_remittance_chain", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        before = [r.brought_forward for r in DailyRemittance.objects.order_by("date")]
        self._run("--dry-run")
        after = [r.brought_forward for r in DailyRemittance.objects.order_by("date")]
        self.assertEqual(before, after)

    def test_it_rebuilds_the_chain_from_the_first_row(self):
        self._run()
        rows = list(DailyRemittance.objects.order_by("date"))
        self.assertAlmostEqual(rows[0].brought_forward, 0.0)
        self.assertAlmostEqual(rows[1].brought_forward, 1200.0)
        self.assertAlmostEqual(rows[2].brought_forward, 2400.0)
        self.assertAlmostEqual(rows[2].total_due, 3600.0)

    def test_only_the_open_row_reports_outstanding(self):
        self._run()
        rows = list(DailyRemittance.objects.order_by("date"))
        self.assertAlmostEqual(rows[0].outstanding, 0.0)
        self.assertAlmostEqual(rows[1].outstanding, 0.0)
        self.assertAlmostEqual(rows[2].outstanding, 3600.0)

    def test_it_never_rewrites_a_target(self):
        self._run()
        for row in DailyRemittance.objects.all():
            self.assertAlmostEqual(row.target_amount, 1200.0)

    def test_from_a_date_treats_earlier_days_as_closed(self):
        self._run("--from", (self.today - timedelta(days=1)).strftime("%Y-%m-%d"))
        last = DailyRemittance.objects.order_by("date").last()
        self.assertAlmostEqual(last.brought_forward, 0.0)
        self.assertAlmostEqual(last.total_due, 1200.0)

    def test_payments_are_never_touched(self):
        RemittancePayment.objects.create(
            remittance=self.rows[0], source="cash", amount=500.0
        )
        self._run()
        self.assertEqual(RemittancePayment.objects.count(), 1)
        self.assertAlmostEqual(
            DailyRemittance.objects.get(pk=self.rows[0].pk).amount_remitted, 500.0
        )


class MultiDaySpanTest(TestCase):
    """
    Roll a branch forward day by day, exactly as the middleware does, and check
    the chain stays coherent across a long span rather than only over two rows.

    The invariant that matters: at every point, the sum of every row's
    `outstanding` equals the single open balance. If that ever drifts, a report
    is counting the same money twice.
    """

    TARGET = 1200.0

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        RemittanceSetup.objects.create(branch=self.branch, target_amount=self.TARGET)
        self.start = timezone.localdate() - timedelta(days=40)
        self.previous = None

    def _roll(self, day_index, net_sales, remit):
        """Open the next day the way the middleware does, then remit."""
        day = self.start + timedelta(days=day_index)
        brought_forward = 0.0
        if self.previous is not None:
            self.previous.recalc()
            brought_forward = self.previous.carry_to_next_day()
        row = DailyRemittance.objects.create(
            branch=self.branch, date=day, target_amount=self.TARGET,
            brought_forward=brought_forward, net_sales=net_sales, is_finalized=True,
        )
        if self.previous is not None:
            self.previous._stamp_carried(brought_forward)
        row.recalc()
        if remit:
            RemittancePayment.objects.create(
                remittance=row, source="cash", amount=remit
            )
            row.refresh_from_db()
        self.previous = row
        return row

    def _rows(self):
        return list(DailyRemittance.objects.order_by("date"))

    def _assert_debt_owed_once(self):
        rows = self._rows()
        self.assertAlmostEqual(
            sum(r.outstanding for r in rows), rows[-1].balance_due, places=2,
            msg="the same balance is being reported on more than one row",
        )

    # ---- a well-run month ----------------------------------------------
    def test_thirty_days_of_remitting_the_target_never_accumulates(self):
        for i in range(30):
            self._roll(i, net_sales=1500.0, remit=self.TARGET)
            self._assert_debt_owed_once()
        rows = self._rows()
        self.assertAlmostEqual(rows[-1].brought_forward, 0.0)
        self.assertAlmostEqual(rows[-1].outstanding, 0.0)
        self.assertTrue(all(r.is_settled for r in rows))
        self.assertAlmostEqual(sum(r.outstanding for r in rows), 0.0)

    # ---- the live complaint --------------------------------------------
    def test_a_stuck_backlog_stays_stuck_while_only_the_target_is_remitted(self):
        """
        Six days nobody entered, then a month of dutifully remitting exactly the
        target. The 7200 never moves — because the target only ever covers the
        day itself. Correct, and now visible instead of mysterious.
        """
        for i in range(6):
            self._roll(i, net_sales=0.0, remit=0.0)
        self.assertAlmostEqual(self.previous.carry_to_next_day(), 7200.0)

        for i in range(6, 36):
            row = self._roll(i, net_sales=1500.0, remit=self.TARGET)
            self._assert_debt_owed_once()
            self.assertAlmostEqual(row.brought_forward, 7200.0)
            self.assertAlmostEqual(row.balance_due, 7200.0)
            # And the page can now say exactly what the 1200 covered.
            split = row.allocation_for()
            self.assertAlmostEqual(split["arrears"], 1200.0)
            self.assertAlmostEqual(split["arrears_left"], 6000.0)

        # Reported across the whole span it is 7200 once, not once per day.
        self.assertAlmostEqual(sum(r.outstanding for r in self._rows()), 7200.0)

    def test_clearing_the_backlog_in_one_go_settles_the_whole_span(self):
        for i in range(6):
            self._roll(i, net_sales=0.0, remit=0.0)
        for i in range(6, 20):
            self._roll(i, net_sales=1500.0, remit=self.TARGET)
        # A good day: hand over the arrears as well as the target.
        row = self._roll(20, net_sales=9000.0, remit=8400.0)
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.balance_due, 0.0)
        self.assertAlmostEqual(sum(r.outstanding for r in self._rows()), 0.0)

        # And it stays clear afterwards.
        after = self._roll(21, net_sales=1500.0, remit=self.TARGET)
        self.assertAlmostEqual(after.brought_forward, 0.0)
        self.assertTrue(after.is_settled)

    # ---- a messy, realistic month --------------------------------------
    def test_a_mixed_month_matches_an_independent_running_balance(self):
        """
        Good days, short days, dead days, over-remittances and a double payment,
        checked against the recurrence computed in plain Python:

            balance = max(0, target + balance - remitted)
        """
        pattern = [
            (1500.0, 1200.0), (800.0, 800.0), (0.0, 0.0), (2000.0, 2000.0),
            (1500.0, 1200.0), (1500.0, 0.0), (3000.0, 2500.0), (900.0, 900.0),
            (0.0, 0.0), (1500.0, 1200.0), (5000.0, 4000.0), (1200.0, 1200.0),
            (600.0, 600.0), (1500.0, 1500.0), (0.0, 0.0), (2200.0, 2200.0),
            (1500.0, 1200.0), (1000.0, 1000.0), (4000.0, 3000.0), (1500.0, 1200.0),
        ]
        expected = 0.0
        for i, (net, remit) in enumerate(pattern):
            row = self._roll(i, net_sales=net, remit=remit)
            expected = max(0.0, self.TARGET + expected - remit)
            self.assertAlmostEqual(
                row.balance_due, expected, places=2,
                msg=f"day {i}: balance drifted from the recurrence",
            )
            self._assert_debt_owed_once()

        self.assertAlmostEqual(self._rows()[-1].balance_due, expected, places=2)

    def test_correcting_one_old_day_repairs_the_whole_span(self):
        for i in range(20):
            self._roll(i, net_sales=1500.0, remit=0.0)      # nothing ever remitted
        rows = self._rows()
        self.assertAlmostEqual(rows[-1].balance_due, self.TARGET * 20)

        # Settle day 5 after the fact; everything after it must come down by 1200.
        RemittancePayment.objects.create(
            remittance=rows[5], source="cash", amount=self.TARGET
        )
        rows = self._rows()
        self.assertAlmostEqual(rows[-1].balance_due, self.TARGET * 19)
        self._assert_debt_owed_once()
        # And every row in between shifted, not just the endpoints.
        self.assertAlmostEqual(rows[10].brought_forward, self.TARGET * 9)

    def test_the_report_over_the_span_shows_the_debt_once(self):
        for i in range(15):
            self._roll(i, net_sales=0.0, remit=0.0)
        rows = self._rows()
        naive = sum(r.total_due - r.amount_remitted for r in rows)
        real = sum(r.outstanding for r in rows)
        self.assertAlmostEqual(real, self.TARGET * 15)
        # The old behaviour would have reported the triangular number: 144000.
        self.assertGreater(naive, real * 5)


class RemittancePageFlowTest(TestCase):
    """
    The whole journey through the page, which is where the complaint surfaced:
    the prefill must offer what is owed, and a part payment must say so.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        RemittanceSetup.objects.create(branch=self.branch, target_amount=1200.0)
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.client.force_login(self.staff)
        self.today = timezone.localdate()

    def _page(self):
        return self.client.get(
            reverse("remittance_list"), {"branch_id": self.branch.id}
        )

    def _row(self):
        return DailyRemittance.objects.get(branch=self.branch, date=self.today)

    def _set_day(self, net_sales, brought_forward=0.0):
        self._page()  # opens today's row
        # Finalised so a later page load doesn't recompute net sales from the
        # (empty) order tables and wipe the figure under the test.
        DailyRemittance.objects.filter(pk=self._row().pk).update(
            net_sales=net_sales, brought_forward=brought_forward, is_finalized=True,
        )
        self._row().recalc()

    def test_prefill_offers_the_target_not_the_days_takings(self):
        self._set_day(net_sales=1500.0)
        suggested = self._page().context["suggested"]
        self.assertEqual([(s["label"], s["amount"]) for s in suggested],
                         [("Target", 1200.0)])

    def test_applying_the_prefill_settles_the_day(self):
        self._set_day(net_sales=1500.0)
        self.client.post(reverse("remittance_apply_suggestion", args=[self._row().pk]))
        row = self._row()
        self.assertAlmostEqual(row.amount_remitted, 1200.0)
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_applying_the_prefill_settles_a_day_carrying_arrears(self):
        """The old prefill offered net sales, so this row could never clear."""
        self._set_day(net_sales=3000.0, brought_forward=1200.0)
        self.client.post(reverse("remittance_apply_suggestion", args=[self._row().pk]))
        row = self._row()
        self.assertAlmostEqual(row.amount_remitted, 2400.0)
        self.assertTrue(row.is_settled)
        self.assertAlmostEqual(row.carry_to_next_day(), 0.0)

    def test_remitting_only_the_target_warns_that_arrears_remain(self):
        self._set_day(net_sales=1500.0, brought_forward=6000.0)
        response = self.client.post(
            reverse("remittance_add_payment", args=[self._row().pk]),
            {"source": "cash", "amount": "1200", "reference": ""},
            follow=True,
        )
        body = " ".join(m.message for m in response.context["messages"])
        self.assertIn("6000.00", body)          # what is still outstanding
        self.assertIn("4800.00", body)          # arrears specifically still unpaid
        self.assertIn("carry", body.lower())

    def test_settling_in_full_says_so(self):
        self._set_day(net_sales=1500.0)
        response = self.client.post(
            reverse("remittance_add_payment", args=[self._row().pk]),
            {"source": "cash", "amount": "1200", "reference": ""},
            follow=True,
        )
        body = " ".join(m.message for m in response.context["messages"])
        self.assertIn("fully settled", body)
