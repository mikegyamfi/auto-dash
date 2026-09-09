from django.test import TestCase

from autodash_App.models import (
    Branch, CustomUser, Expense, Utility, UtilityReading,
    find_utility_for_expense, looks_like_topup,
)


class TopupMatchingTest(TestCase):
    """Which expense lines read as buying utility credit, and for which utility."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.electricity = Utility.objects.create(
            branch=self.branch, name="Electricity", unit="GHS", cost_per_unit=1.0,
            topup_keywords="ECG, power, light",
        )
        self.water = Utility.objects.create(
            branch=self.branch, name="Water", unit="GHS", cost_per_unit=1.0,
            topup_keywords="GWCL",
        )

    def _expense(self, description, amount=100.0, **kw):
        return Expense.objects.create(
            branch=self.branch, description=description, amount=amount, **kw
        )

    def test_marker_detection(self):
        for text in ("ECG Prepaid", "Water topup", "Water Top Up", "top-up",
                     "recharge", "bought credit"):
            self.assertTrue(looks_like_topup(text), text)
        for text in ("Water bottles", "[Recurring] Water", "Brooms", ""):
            self.assertFalse(looks_like_topup(text), text)

    def test_an_alias_reaches_a_differently_named_utility(self):
        """'ECG Prepaid' must find a utility called Electricity."""
        expense = self._expense("ECG Prepaid Topup")
        self.assertEqual(find_utility_for_expense(expense), self.electricity)

    def test_the_utility_name_itself_matches(self):
        expense = self._expense("Water topup")
        self.assertEqual(find_utility_for_expense(expense), self.water)

    def test_case_does_not_matter(self):
        self.assertEqual(
            find_utility_for_expense(self._expense("ecg PREPAID")), self.electricity
        )

    def test_an_ordinary_line_naming_a_utility_is_not_a_topup(self):
        """
        The live data has dozens of '[Recurring] Water' rows. Matching on the
        utility name alone would turn every one into a water purchase.
        """
        for text in ("[Recurring] Water", "Water bottles for staff",
                     "Electricity bill dispute"):
            self.assertIsNone(find_utility_for_expense(self._expense(text)), text)

    def test_a_topup_naming_no_utility_matches_nothing(self):
        self.assertIsNone(find_utility_for_expense(self._expense("Airtime topup")))

    def test_auto_generated_expenses_are_never_topups(self):
        expense = self._expense("ECG Prepaid Topup", is_auto_generated=True)
        self.assertIsNone(find_utility_for_expense(expense))

    def test_another_branchs_utility_is_not_matched(self):
        other = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        expense = Expense.objects.create(
            branch=other, description="ECG Prepaid Topup", amount=100.0
        )
        self.assertIsNone(find_utility_for_expense(expense))


class TopupBecomesPurchaseTest(TestCase):
    """The matched amount lands on that day's reading as a purchase."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )
        self.electricity = Utility.objects.create(
            branch=self.branch, name="Electricity", unit="GHS", cost_per_unit=1.0,
            topup_keywords="ECG",
        )

    def _topup(self, amount=100.0, description="ECG Prepaid Topup"):
        return Expense.objects.create(
            branch=self.branch, description=description, amount=amount, user=self.user
        )

    def test_it_creates_the_days_reading_with_the_purchase(self):
        expense = self._topup(100.0)

        reading = UtilityReading.objects.get(utility=self.electricity, date=expense.date)
        self.assertAlmostEqual(reading.auto_purchase, 100.0)
        self.assertAlmostEqual(reading.total_purchase, 100.0)
        expense.refresh_from_db()
        self.assertEqual(expense.topup_reading, reading)

    def test_buying_credit_consumes_nothing(self):
        """A new reading closes where it opened plus what was bought."""
        expense = self._topup(100.0)
        reading = UtilityReading.objects.get(utility=self.electricity, date=expense.date)
        self.assertAlmostEqual(reading.usage, 0.0)
        self.assertAlmostEqual(reading.closing_balance, 100.0)

    def test_it_adds_to_an_existing_reading_without_touching_the_typed_purchase(self):
        reading = UtilityReading.objects.create(
            utility=self.electricity, branch=self.branch,
            opening_balance=50.0, purchase=20.0, closing_balance=40.0,
        )
        expense = Expense.objects.create(
            branch=self.branch, description="ECG Prepaid Topup",
            amount=100.0, user=self.user,
        )
        # The expense date and the reading date are both today.
        self.assertEqual(expense.date, reading.date)

        reading.refresh_from_db()
        self.assertAlmostEqual(reading.purchase, 20.0)       # typed value untouched
        self.assertAlmostEqual(reading.auto_purchase, 100.0)
        self.assertAlmostEqual(reading.total_purchase, 120.0)
        self.assertAlmostEqual(reading.usage, 130.0)          # 50 + 120 - 40

    def test_two_topups_on_one_day_are_totalled(self):
        self._topup(100.0)
        self._topup(40.0, "ECG prepaid recharge")

        reading = UtilityReading.objects.get(utility=self.electricity)
        self.assertAlmostEqual(reading.auto_purchase, 140.0)

    def test_editing_the_amount_retotals_the_reading(self):
        expense = self._topup(100.0)
        expense.amount = 250.0
        expense.save()

        reading = UtilityReading.objects.get(utility=self.electricity)
        self.assertAlmostEqual(reading.auto_purchase, 250.0)

    def test_deleting_the_expense_removes_the_purchase(self):
        expense = self._topup(100.0)
        reading = UtilityReading.objects.get(utility=self.electricity)
        expense.delete()

        reading.refresh_from_db()
        self.assertAlmostEqual(reading.auto_purchase, 0.0)

    def test_redescribing_it_away_from_a_topup_detaches_it(self):
        expense = self._topup(100.0)
        reading = UtilityReading.objects.get(utility=self.electricity)

        expense.description = "Brooms and mops"
        expense.save()

        expense.refresh_from_db()
        self.assertIsNone(expense.topup_reading)
        reading.refresh_from_db()
        self.assertAlmostEqual(reading.auto_purchase, 0.0)

    def test_it_does_not_recurse_through_the_usage_expense(self):
        """
        A reading books an auto-generated usage Expense, which fires this same
        signal. It must not be treated as a top-up.
        """
        UtilityReading.objects.create(
            utility=self.electricity, branch=self.branch,
            opening_balance=100.0, purchase=0.0, closing_balance=70.0,
        )
        usage_expense = Expense.objects.get(branch=self.branch, is_auto_generated=True)
        self.assertIsNone(usage_expense.topup_reading)
        self.assertAlmostEqual(usage_expense.amount, 30.0)
