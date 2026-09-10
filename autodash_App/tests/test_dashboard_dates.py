from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autodash_App.models import Branch, CustomUser, Worker, WorkerCategory


class DashboardDateScopeTest(TestCase):
    """
    Staff read a date range; a branch admin reads one day at a time. The limit
    is enforced server-side, so a hand-typed URL cannot widen it.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.category = WorkerCategory.objects.create(name="Washer", service_provider=True)

        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.branch_admin_user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="worker", approved=True
        )
        Worker.objects.create(
            user=self.branch_admin_user, branch=self.branch,
            worker_category=self.category, is_branch_admin=True,
        )

        self.today = timezone.localdate()
        self.week_ago = self.today - timedelta(days=7)

    def _get(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("index"), params)

    # ---- staff keep the range -------------------------------------------
    def test_staff_can_read_a_range(self):
        r = self._get(self.staff,
                      start_date=self.week_ago.strftime("%Y-%m-%d"),
                      end_date=self.today.strftime("%Y-%m-%d"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["can_pick_range"])
        self.assertEqual(r.context["start_dt"], self.week_ago)
        self.assertEqual(r.context["end_dt"], self.today)

    def test_staff_see_both_date_inputs(self):
        r = self._get(self.staff)
        self.assertContains(r, 'id="end_date"')
        self.assertContains(r, "Start Date")
        self.assertContains(r, "End Date")

    # ---- branch admins get a single day ---------------------------------
    def test_a_branch_admin_range_collapses_to_one_day(self):
        r = self._get(self.branch_admin_user,
                      start_date=self.week_ago.strftime("%Y-%m-%d"),
                      end_date=self.today.strftime("%Y-%m-%d"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["can_pick_range"])
        self.assertEqual(r.context["start_dt"], self.week_ago)
        self.assertEqual(r.context["end_dt"], self.week_ago)

    def test_a_branch_admin_cannot_widen_it_by_url(self):
        """The end date is ignored server-side, not just hidden in the form."""
        r = self._get(self.branch_admin_user,
                      start_date=self.today.strftime("%Y-%m-%d"),
                      end_date=(self.today + timedelta(days=30)).strftime("%Y-%m-%d"))
        self.assertEqual(r.context["start_dt"], r.context["end_dt"])

    def test_a_branch_admin_sees_one_date_field(self):
        r = self._get(self.branch_admin_user)
        self.assertContains(r, ">\n      Date\n    <", html=False)
        self.assertNotContains(r, "End Date")
        # The hidden pair keeps the posted dates in step.
        self.assertContains(r, 'type="hidden" name="end_date"')

    def test_it_defaults_to_today_for_both(self):
        for user in (self.staff, self.branch_admin_user):
            r = self._get(user)
            self.assertEqual(r.context["start_dt"], self.today)
            self.assertEqual(r.context["end_dt"], self.today)

    def test_the_inputs_echo_the_dates_actually_used(self):
        r = self._get(self.branch_admin_user,
                      start_date=self.week_ago.strftime("%Y-%m-%d"),
                      end_date=self.today.strftime("%Y-%m-%d"))
        self.assertEqual(r.context["start_date_str"], self.week_ago.strftime("%Y-%m-%d"))
        self.assertEqual(r.context["end_date_str"], self.week_ago.strftime("%Y-%m-%d"))
