from django.test import TestCase

from autodash_App.forms import OtherServiceForm
from autodash_App.models import (
    Arrears, Branch, CustomUser, OtherService, Revenue, Worker, WorkerCategory,
)


class OtherServicePaymentTest(TestCase):
    """Tender breakdown on non-catalogue jobs."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )

    def _job(self, **kwargs):
        defaults = dict(
            user=self.user,
            branch=self.branch,
            service_name="Engine steam wash",
            amount=200.0,
            status="completed",
        )
        defaults.update(kwargs)
        return OtherService.objects.create(**defaults)

    def test_amount_paid_sums_the_three_tenders(self):
        job = self._job(cash_paid=50.0, momo_amount=100.0, card_amount=50.0)
        self.assertAlmostEqual(job.amount_paid, 200.0)

    def test_infer_payment_method_single_and_split(self):
        self.assertEqual(self._job(cash_paid=200.0).infer_payment_method(), "cash")
        self.assertEqual(self._job(momo_amount=200.0).infer_payment_method(), "momo")
        self.assertEqual(self._job(card_amount=200.0).infer_payment_method(), "card")
        self.assertEqual(
            self._job(cash_paid=100.0, momo_amount=100.0).infer_payment_method(), "split"
        )
        self.assertIsNone(self._job().infer_payment_method())


class OtherServiceFormPaymentTest(TestCase):
    """The form is what enforces that the split reconciles to the amount."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        # A job must record who did it, so every payload carries a worker.
        self.worker = Worker.objects.create(
            user=CustomUser.objects.create_user(
                username="0241111111", password="x", role="worker"
            ),
            branch=self.branch,
            worker_category=WorkerCategory.objects.create(
                name="Washer", service_provider=True
            ),
        )

    def _post(self, **overrides):
        data = {
            "service_name": "Engine steam wash",
            "amount": "200",
            "commission_rate": "0",
            "contact_name": "",
            "contact_phone": "",
            "notes": "",
            "status": "completed",
            "workers": [str(self.worker.id)],
            "cash_paid": "200",
            "momo_amount": "0",
            "card_amount": "0",
        }
        data.update(overrides)
        return OtherServiceForm(data, branch=self.branch, show_branch=False)

    def test_completed_job_with_matching_split_is_valid(self):
        form = self._post(cash_paid="120", momo_amount="80")
        self.assertTrue(form.is_valid(), form.errors)

    def test_completed_job_with_short_split_is_rejected(self):
        form = self._post(cash_paid="120", momo_amount="0")
        self.assertFalse(form.is_valid())
        self.assertIn("must add up to the amount", str(form.errors))

    def test_on_credit_job_must_not_carry_payment(self):
        form = self._post(status="onCredit", cash_paid="200")
        self.assertFalse(form.is_valid())
        self.assertIn("on-credit job is unpaid", str(form.errors))

    def test_on_credit_job_with_no_payment_is_valid(self):
        form = self._post(status="onCredit", cash_paid="0")
        self.assertTrue(form.is_valid(), form.errors)

    def test_saving_derives_the_payment_method(self):
        form = self._post(cash_paid="150", momo_amount="50")
        self.assertTrue(form.is_valid(), form.errors)
        job = form.save(commit=False)
        self.assertEqual(job.payment_method, "split")


class OtherServiceArrearsTest(TestCase):
    """On-credit non-catalogue jobs are tracked as debt, and can be settled."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )

    def _job(self, status="onCredit", amount=200.0):
        return OtherService.objects.create(
            user=self.user,
            branch=self.branch,
            service_name="Engine steam wash",
            amount=amount,
            status=status,
            contact_name="Ama Mensah",
            contact_phone="0241111111",
        )

    def test_on_credit_job_creates_arrears_and_no_revenue(self):
        job = self._job()

        arrears = Arrears.objects.get(other_service=job)
        self.assertAlmostEqual(arrears.amount_owed, 200.0)
        self.assertFalse(arrears.is_paid)
        self.assertEqual(arrears.branch, self.branch)
        self.assertFalse(Revenue.objects.filter(other_service=job).exists())

    def test_completed_job_creates_no_arrears(self):
        job = self._job(status="completed")
        self.assertFalse(Arrears.objects.filter(other_service=job).exists())
        self.assertTrue(Revenue.objects.filter(other_service=job).exists())

    def test_moving_off_credit_clears_an_unpaid_debt(self):
        job = self._job()
        self.assertTrue(Arrears.objects.filter(other_service=job).exists())

        job.mark_canceled()

        self.assertFalse(Arrears.objects.filter(other_service=job).exists())

    def test_editing_the_amount_updates_the_debt(self):
        job = self._job()
        job.amount = 350.0
        job.save()

        self.assertAlmostEqual(
            Arrears.objects.get(other_service=job).amount_owed, 350.0
        )

    def test_settled_debt_is_never_deleted_by_a_status_change(self):
        job = self._job()
        arrears = Arrears.objects.get(other_service=job)
        arrears.is_paid = True
        arrears.save()

        job.mark_canceled()

        self.assertTrue(Arrears.objects.filter(pk=arrears.pk).exists())

    def test_mark_as_paid_records_revenue_for_the_job(self):
        job = self._job()
        arrears = Arrears.objects.get(other_service=job)

        arrears.mark_as_paid()

        arrears.refresh_from_db()
        self.assertTrue(arrears.is_paid)
        revenue = Revenue.objects.get(other_service=job)
        self.assertAlmostEqual(revenue.final_amount, 200.0)

    def test_display_helpers_describe_the_job(self):
        job = self._job()
        arrears = Arrears.objects.get(other_service=job)

        self.assertTrue(arrears.is_other_service)
        self.assertEqual(arrears.display_reference, f"OS-{job.pk}")
        self.assertEqual(arrears.display_description, "Engine steam wash")
        self.assertEqual(arrears.display_customer_name, "Ama Mensah")
        self.assertEqual(arrears.display_customer_phone, "0241111111")
        self.assertEqual(arrears.job, job)
