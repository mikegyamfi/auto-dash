from django.test import TestCase
from django.urls import reverse

from autodash_App.models import (
    Arrears, Branch, CustomUser, OtherService, Worker, WorkerCategory,
)


class OtherServicePageSmokeTest(TestCase):
    """
    The arrears and other-service pages now render rows that have no service
    order behind them. These guard the template changes against attribute
    errors on that path.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="secret", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        self.client.force_login(self.staff)

        self.job = OtherService.objects.create(
            user=self.staff,
            branch=self.branch,
            service_name="Engine steam wash",
            amount=200.0,
            status="onCredit",
            contact_name="Ama Mensah",
            contact_phone="0241111111",
        )

    def test_on_credit_job_produced_an_arrears_row(self):
        self.assertTrue(Arrears.objects.filter(other_service=self.job).exists())

    def test_admin_arrears_list_renders_an_other_service_debt(self):
        response = self.client.get(reverse("arrears_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"OS-{self.job.pk}")

    def test_other_service_history_renders(self):
        response = self.client.get(reverse("other_service_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Engine steam wash")
        self.assertContains(response, "On credit")

    def test_arrears_details_json_for_an_other_service(self):
        arrears = Arrears.objects.get(other_service=self.job)
        response = self.client.get(reverse("arrears_details", args=[arrears.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["order_number"], f"OS-{self.job.pk}")
        self.assertEqual(data["customer"], "Ama Mensah")
        self.assertEqual(data["final_amount"], 200.0)
        self.assertIsNone(data["vehicle"])

    def test_completed_job_shows_its_tender_on_the_history_page(self):
        job = OtherService.objects.create(
            user=self.staff,
            branch=self.branch,
            service_name="Tyre polish",
            amount=100.0,
            status="completed",
            cash_paid=60.0,
            momo_amount=40.0,
            payment_method="split",
        )
        response = self.client.get(reverse("other_service_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Split")
