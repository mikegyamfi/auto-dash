from django.test import TestCase
from django.urls import reverse

from autodash_App.forms import OtherServiceForm
from autodash_App.models import (
    Branch, CustomUser, OtherService, Worker, WorkerCategory,
)


class OtherServiceWorkersRequiredTest(TestCase):
    """
    A job used to save with nobody on it: the Workers column rendered blank and
    the job silently paid no commission.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.category = WorkerCategory.objects.create(name="Washer", service_provider=True)
        self.worker = Worker.objects.create(
            user=CustomUser.objects.create_user(username="0241111111", password="x", role="worker"),
            branch=self.branch, worker_category=self.category,
        )

    def _form(self, workers):
        return OtherServiceForm({
            "service_name": "Polytank Wash", "amount": "100", "commission_rate": "10",
            "contact_name": "", "contact_phone": "", "notes": "", "status": "completed",
            "workers": workers, "cash_paid": "100", "momo_amount": "0", "card_amount": "0",
        }, branch=self.branch, show_branch=False)

    def test_a_job_with_no_workers_is_rejected(self):
        form = self._form([])
        self.assertFalse(form.is_valid())
        self.assertIn("workers", form.errors)

    def test_a_job_with_workers_is_accepted(self):
        self.assertTrue(self._form([str(self.worker.id)]).is_valid())


class OtherServiceDetailsPageTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.other_branch = Branch.objects.create(
            name="Other Branch", location="Kumasi", phone_number="0240000001"
        )
        self.provider = WorkerCategory.objects.create(name="Washer", service_provider=True)
        self.non_provider = WorkerCategory.objects.create(name="Receptionist", service_provider=False)
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.washer = self._worker("0241111111", "Kojo", "Manu", self.provider)
        self.helper = self._worker("0242222222", "Ama", "Boateng", self.non_provider)

        self.job = OtherService.objects.create(
            user=self.staff, branch=self.branch, service_name="Polytank Wash",
            amount=200.0, commission_rate=10.0, status="completed",
            cash_paid=200.0, payment_method="cash",
        )
        self.job.workers.set([self.washer, self.helper])
        self.client.force_login(self.staff)

    def _worker(self, username, first, last, category, branch=None):
        user = CustomUser.objects.create_user(
            username=username, password="x", role="worker",
            first_name=first, last_name=last,
        )
        return Worker.objects.create(
            user=user, branch=branch or self.branch, worker_category=category
        )

    def test_details_page_renders(self):
        r = self.client.get(reverse("other_service_details", args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Polytank Wash")
        self.assertContains(r, f"OS-{self.job.pk}")

    def test_it_lists_the_workers_and_what_they_earned(self):
        r = self.client.get(reverse("other_service_details", args=[self.job.pk]))
        self.assertContains(r, "Kojo Manu")
        self.assertContains(r, "20.00")  # 10% of 200, one eligible worker

    def test_a_non_eligible_worker_is_shown_but_unpaid(self):
        """They worked the job; they're just not in a commission-eligible category."""
        r = self.client.get(reverse("other_service_details", args=[self.job.pk]))
        self.assertContains(r, "Ama Boateng")
        self.assertContains(r, "not commission-eligible")

    def test_it_shows_the_payment_breakdown(self):
        r = self.client.get(reverse("other_service_details", args=[self.job.pk]))
        self.assertContains(r, "Cash")
        self.assertContains(r, "200.00")

    def test_an_on_credit_job_shows_its_arrears(self):
        job = OtherService.objects.create(
            user=self.staff, branch=self.branch, service_name="Tyre polish",
            amount=150.0, status="onCredit",
        )
        job.workers.set([self.washer])
        r = self.client.get(reverse("other_service_details", args=[job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Arrears")
        self.assertContains(r, "Outstanding")

    def test_a_job_with_no_workers_says_so_plainly(self):
        job = OtherService.objects.create(
            user=self.staff, branch=self.branch, service_name="Ad-hoc job",
            amount=50.0, status="completed", cash_paid=50.0,
        )
        r = self.client.get(reverse("other_service_details", args=[job.pk]))
        self.assertContains(r, "No workers were recorded")

    def test_a_worker_cannot_view_another_branchs_job(self):
        outsider = self._worker("0243333333", "Yaw", "Osei", self.provider,
                                branch=self.other_branch)
        self.client.force_login(outsider.user)
        r = self.client.get(reverse("other_service_details", args=[self.job.pk]))
        self.assertRedirects(r, reverse("other_service_history"))

    def test_history_pages_link_to_it(self):
        for name in ("other_service_history", "service_history"):
            r = self.client.get(reverse(name))
            self.assertContains(
                r, reverse("other_service_details", args=[self.job.pk]),
                msg_prefix=f"{name} should link to the details page",
            )
