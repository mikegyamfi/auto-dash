"""
The utilities page defaults to every branch.

Previously `_utility_scope` silently fell back to the first branch, so staff
opening Utilities saw one branch's meters with nothing saying so. Now no choice
means all of them, added up, and picking one narrows to it — the same rule the
petty cash page and the remittance report already follow.

Pages that *write* (taking a reading) still resolve to a single branch; "all
branches" is not a place to save a meter reading.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autodash_App.models import (
    Branch, CustomUser, Utility, UtilityReading, Worker, WorkerCategory,
)


class UtilitiesBranchScopeTest(TestCase):

    def setUp(self):
        self.ridge = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.teshie = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        self.today = timezone.localdate()

        self.ridge_power = Utility.objects.create(
            branch=self.ridge, name="Electricity", unit="kWh", cost_per_unit=2.0
        )
        self.teshie_power = Utility.objects.create(
            branch=self.teshie, name="Electricity", unit="kWh", cost_per_unit=2.0
        )
        self.ridge_water = Utility.objects.create(
            branch=self.ridge, name="Water", unit="m3", cost_per_unit=5.0
        )

        # Ridge burns 30 kWh, Teshie 20 kWh, Ridge 4 m3 of water.
        self._reading(self.ridge_power, opening=100.0, closing=70.0)
        self._reading(self.teshie_power, opening=50.0, closing=30.0)
        self._reading(self.ridge_water, opening=10.0, closing=6.0)

        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.client.force_login(self.staff)

    def _reading(self, utility, opening, closing, days_ago=1):
        return UtilityReading.objects.create(
            utility=utility, branch=utility.branch,
            date=self.today - timedelta(days=days_ago),
            opening_balance=opening, closing_balance=closing,
        )

    def _get(self, **params):
        return self.client.get(reverse("utilities_list"), params)

    # ---- the default ----------------------------------------------------
    def test_no_branch_chosen_shows_every_branch(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_all"])
        self.assertIsNone(response.context["branch"])
        self.assertEqual(len(response.context["readings"]), 3)

    def test_it_does_not_silently_fall_back_to_the_first_branch(self):
        self.assertIsNone(self._get().context["branch"])

    def test_the_page_says_it_is_showing_all_branches(self):
        self.assertContains(self._get(), "All branches")

    def test_the_trail_names_the_branch_when_unfiltered(self):
        response = self._get()
        self.assertContains(response, "Ridge")
        self.assertContains(response, "Teshie")

    # ---- the accumulation ----------------------------------------------
    def test_the_same_utility_is_added_up_across_branches(self):
        combined = {c["name"]: c for c in self._get().context["combined"]}
        self.assertAlmostEqual(combined["Electricity"]["total_usage"], 50.0)
        self.assertEqual(combined["Electricity"]["branches"], 2)

    def test_a_utility_at_one_branch_only_is_still_listed(self):
        combined = {c["name"]: c for c in self._get().context["combined"]}
        self.assertAlmostEqual(combined["Water"]["total_usage"], 4.0)
        self.assertEqual(combined["Water"]["branches"], 1)

    def test_balances_on_hand_are_summed(self):
        combined = {c["name"]: c for c in self._get().context["combined"]}
        self.assertAlmostEqual(combined["Electricity"]["current_balance"], 100.0)

    def test_cost_is_totalled_across_everything(self):
        # 50 kWh at 2.00 + 4 m3 at 5.00
        self.assertAlmostEqual(self._get().context["totals"]["cost"], 120.0)

    def test_spend_is_broken_down_per_branch(self):
        by_branch = {b["branch"].name: b for b in self._get().context["by_branch"]}
        self.assertAlmostEqual(by_branch["Ridge"]["cost"], 80.0)   # 30*2 + 4*5
        self.assertAlmostEqual(by_branch["Teshie"]["cost"], 40.0)  # 20*2

    def test_the_branch_breakdown_adds_up_to_the_total(self):
        context = self._get().context
        self.assertAlmostEqual(
            sum(b["cost"] for b in context["by_branch"]),
            context["totals"]["cost"],
        )

    # ---- filtering ------------------------------------------------------
    def test_choosing_a_branch_narrows_to_it(self):
        response = self._get(branch_id=self.ridge.id)
        self.assertFalse(response.context["show_all"])
        self.assertEqual(response.context["branch"], self.ridge)
        self.assertEqual(len(response.context["readings"]), 2)

    def test_a_filtered_view_totals_only_that_branch(self):
        response = self._get(branch_id=self.teshie.id)
        self.assertAlmostEqual(response.context["totals"]["cost"], 40.0)

    def test_a_filtered_view_drops_the_aggregate_panels(self):
        response = self._get(branch_id=self.ridge.id)
        self.assertEqual(response.context["combined"], [])
        self.assertEqual(response.context["by_branch"], [])

    def test_filtering_by_utility_still_works(self):
        response = self._get(utility=self.ridge_water.id)
        self.assertEqual(len(response.context["readings"]), 1)
        self.assertAlmostEqual(response.context["totals"]["usage"], 4.0)

    def test_a_date_range_narrows_the_trail(self):
        older = self.today - timedelta(days=40)
        self._reading(self.ridge_power, opening=200.0, closing=150.0, days_ago=40)
        response = self._get(
            start_date=older.strftime("%Y-%m-%d"),
            end_date=older.strftime("%Y-%m-%d"),
        )
        self.assertEqual(len(response.context["readings"]), 1)


class UtilitiesWorkerScopeTest(TestCase):
    """A plain worker is pinned to their own branch and never sees the aggregate."""

    def setUp(self):
        self.ridge = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.teshie = Branch.objects.create(
            name="Teshie", location="Accra", phone_number="0240000001"
        )
        today = timezone.localdate()
        for branch in (self.ridge, self.teshie):
            util = Utility.objects.create(
                branch=branch, name="Electricity", unit="kWh", cost_per_unit=2.0
            )
            UtilityReading.objects.create(
                utility=util, branch=branch, date=today - timedelta(days=1),
                opening_balance=100.0, closing_balance=80.0,
            )

        category = WorkerCategory.objects.create(name="Washer", service_provider=True)
        user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="worker", approved=True
        )
        Worker.objects.create(user=user, branch=self.ridge, worker_category=category)
        self.client.force_login(user)

    def test_a_worker_sees_only_their_own_branch(self):
        response = self.client.get(reverse("utilities_list"))
        self.assertFalse(response.context["show_all"])
        self.assertEqual(response.context["branch"], self.ridge)
        self.assertEqual(len(response.context["readings"]), 1)

    def test_a_worker_cannot_widen_it_by_url(self):
        response = self.client.get(reverse("utilities_list"), {"branch_id": ""})
        self.assertEqual(response.context["branch"], self.ridge)

    def test_a_worker_cannot_view_another_branch(self):
        response = self.client.get(
            reverse("utilities_list"), {"branch_id": self.teshie.id}
        )
        self.assertEqual(response.context["branch"], self.ridge)

    def test_taking_a_reading_still_resolves_to_one_branch(self):
        """'All branches' is not a place to save a meter reading."""
        response = self.client.get(reverse("utility_reading_create"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["branch"], self.ridge)
