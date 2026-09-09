from django.test import TestCase
from django.urls import reverse

from autodash_App.models import (
    Branch, CustomUser, Expense, PettyCashAccount, PettyCashTransaction,
    Utility, UtilityReading, Worker, WorkerCategory,
)


class PettyCashBalanceTest(TestCase):
    """Expenses draw down a real float; top-ups put money back."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )
        self.account = PettyCashAccount.objects.create(
            branch=self.branch, low_threshold=20.0
        )

    def _topup(self, amount, **kw):
        return PettyCashTransaction.objects.create(
            account=self.account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=amount, **kw
        )

    def _expense(self, amount, **kw):
        return Expense.objects.create(
            branch=self.branch, description="Cleaning supplies",
            amount=amount, user=self.user, **kw
        )

    def test_topup_increases_the_float(self):
        self._topup(100.0)
        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 100.0)

    def test_an_expense_draws_the_float_down(self):
        self._topup(100.0)
        self._expense(30.0)

        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 70.0)

    def test_the_expense_creates_a_traceable_movement(self):
        self._topup(100.0)
        expense = self._expense(30.0)

        txn = PettyCashTransaction.objects.get(expense=expense)
        self.assertEqual(txn.kind, PettyCashTransaction.KIND_EXPENSE)
        self.assertAlmostEqual(txn.amount, 30.0)
        self.assertAlmostEqual(txn.signed_amount, -30.0)
        self.assertAlmostEqual(txn.balance_after, 70.0)
        self.assertEqual(txn.description, "Cleaning supplies")

    def test_editing_an_expense_moves_the_float_not_stacks_it(self):
        self._topup(100.0)
        expense = self._expense(30.0)

        expense.amount = 50.0
        expense.save()

        self.assertEqual(PettyCashTransaction.objects.filter(expense=expense).count(), 1)
        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 50.0)

    def test_deleting_an_expense_returns_the_cash(self):
        self._topup(100.0)
        expense = self._expense(30.0)
        expense.delete()

        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 100.0)

    def test_running_balance_is_stamped_on_every_movement(self):
        self._topup(100.0)
        self._expense(30.0)
        self._expense(20.0)

        balances = list(
            self.account.transactions.order_by("date", "id")
            .values_list("balance_after", flat=True)
        )
        self.assertEqual(balances, [100.0, 70.0, 50.0])


class PettyCashThresholdTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.account = PettyCashAccount.objects.create(
            branch=self.branch, low_threshold=20.0
        )
        PettyCashTransaction.objects.create(
            account=self.account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=100.0,
        )
        self.account.refresh_from_db()

    def _spend(self, amount):
        Expense.objects.create(
            branch=self.branch, description="Spend", amount=amount
        )
        self.account.refresh_from_db()

    def test_healthy_float_is_ok(self):
        self.assertEqual(self.account.status, "ok")
        self.assertFalse(self.account.needs_topup)

    def test_falling_to_the_threshold_flags_low(self):
        self._spend(80.0)  # 100 -> 20, exactly at the threshold
        self.assertEqual(self.account.status, "low")
        self.assertTrue(self.account.needs_topup)
        self.assertAlmostEqual(self.account.shortfall, 0.0)

    def test_falling_below_the_threshold_flags_low_with_a_shortfall(self):
        self._spend(85.0)  # -> 15
        self.assertEqual(self.account.status, "low")
        self.assertAlmostEqual(self.account.shortfall, 5.0)

    def test_overspending_is_recorded_not_blocked(self):
        """The money really left the tin; refusing to record it loses the fact."""
        self._spend(140.0)
        self.assertEqual(self.account.status, "overdrawn")
        self.assertTrue(self.account.is_overdrawn)
        self.assertAlmostEqual(self.account.balance, -40.0)
        self.assertAlmostEqual(self.account.shortfall, 60.0)

    def test_a_topup_clears_the_warning(self):
        self._spend(90.0)
        self.assertTrue(self.account.needs_topup)

        PettyCashTransaction.objects.create(
            account=self.account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=100.0,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, "ok")


class PettyCashScopeTest(TestCase):
    """Only expenses a person entered draw down the float."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.account = PettyCashAccount.objects.create(
            branch=self.branch, low_threshold=20.0
        )
        PettyCashTransaction.objects.create(
            account=self.account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=100.0,
        )

    def test_auto_generated_utility_expense_does_not_touch_the_float(self):
        """
        Utility usage is a computed consumption cost, not cash handed over —
        the cash left when the credit was bought.
        """
        utility = Utility.objects.create(
            branch=self.branch, name="Electricity", unit="units", cost_per_unit=2.0
        )
        UtilityReading.objects.create(
            utility=utility, branch=self.branch,
            opening_balance=100.0, purchase=0.0, closing_balance=90.0,
        )
        # The reading booked an Expense...
        self.assertTrue(
            Expense.objects.filter(branch=self.branch, is_auto_generated=True).exists()
        )
        # ...but the float is untouched.
        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 100.0)

    def test_a_branch_with_no_float_records_expenses_as_before(self):
        other = Branch.objects.create(
            name="No Float", location="Kumasi", phone_number="0240000001"
        )
        expense = Expense.objects.create(
            branch=other, description="Spend", amount=50.0
        )
        self.assertFalse(PettyCashTransaction.objects.filter(expense=expense).exists())

    def test_switching_the_float_off_stops_it_drawing_down(self):
        self.account.is_active = False
        self.account.save()

        Expense.objects.create(branch=self.branch, description="Spend", amount=30.0)

        self.account.refresh_from_db()
        self.assertAlmostEqual(self.account.balance, 100.0)


class PettyCashPagesTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.category = WorkerCategory.objects.create(name="Washer", service_provider=True)
        self.admin_user = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker", approved=True
        )
        self.branch_admin = Worker.objects.create(
            user=self.admin_user, branch=self.branch,
            worker_category=self.category, is_branch_admin=True,
        )
        self.plain_user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="worker", approved=True
        )
        Worker.objects.create(
            user=self.plain_user, branch=self.branch, worker_category=self.category
        )

    def test_dashboard_offers_to_open_a_float_when_there_is_none(self):
        self.client.force_login(self.admin_user)
        r = self.client.get(reverse("petty_cash_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No petty cash float")

    def test_branch_admin_can_open_and_top_up_a_float(self):
        self.client.force_login(self.admin_user)

        self.client.post(reverse("petty_cash_setup"), {
            "low_threshold": "20", "is_active": "on",
        })
        account = PettyCashAccount.objects.get(branch=self.branch)
        self.assertAlmostEqual(account.low_threshold, 20.0)

        self.client.post(reverse("petty_cash_topup"), {
            "kind": "topup", "amount": "100", "date": "2026-09-09", "note": "from the safe",
        })
        account.refresh_from_db()
        self.assertAlmostEqual(account.balance, 100.0)

    def test_a_plain_worker_can_look_but_not_top_up(self):
        PettyCashAccount.objects.create(branch=self.branch, low_threshold=20.0)
        self.client.force_login(self.plain_user)

        r = self.client.get(reverse("petty_cash_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Only branch admins")

        self.client.post(reverse("petty_cash_topup"), {
            "kind": "topup", "amount": "500", "date": "2026-09-09",
        })
        account = PettyCashAccount.objects.get(branch=self.branch)
        self.assertAlmostEqual(account.balance, 0.0)

    def test_an_adjustment_needs_a_reason(self):
        from autodash_App.forms import PettyCashTopUpForm
        form = PettyCashTopUpForm({
            "kind": "adjustment", "amount": "5", "direction": "-1",
            "date": "2026-09-09", "note": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("note", form.errors)

    def test_a_downward_adjustment_reduces_the_float(self):
        account = PettyCashAccount.objects.create(branch=self.branch, low_threshold=20.0)
        PettyCashTransaction.objects.create(
            account=account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=100.0,
        )
        self.client.force_login(self.admin_user)
        self.client.post(reverse("petty_cash_topup"), {
            "kind": "adjustment", "amount": "5", "direction": "-1",
            "date": "2026-09-09", "note": "count was short",
        })
        account.refresh_from_db()
        self.assertAlmostEqual(account.balance, 95.0)

    def test_the_ledger_shows_what_the_money_went_on(self):
        account = PettyCashAccount.objects.create(branch=self.branch, low_threshold=20.0)
        PettyCashTransaction.objects.create(
            account=account, branch=self.branch,
            kind=PettyCashTransaction.KIND_TOPUP, amount=100.0,
        )
        Expense.objects.create(
            branch=self.branch, description="Bought brooms", amount=30.0
        )

        self.client.force_login(self.admin_user)
        r = self.client.get(reverse("petty_cash_dashboard"))
        self.assertContains(r, "Bought brooms")
        self.assertContains(r, "Top-up")
