from django.test import TestCase

from autodash_App.models import (
    Branch, Commission, CustomUser, OtherService, Service, ServiceRendered,
    ServiceRenderedOrder, Worker, WorkerCategory,
)


class OtherServiceCommissionTest(TestCase):
    """Commission on non-catalogue jobs: who earns, when, and how much."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.provider_cat = WorkerCategory.objects.create(
            name="Washer", service_provider=True
        )
        self.non_provider_cat = WorkerCategory.objects.create(
            name="Receptionist", service_provider=False
        )
        self.logger = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )

    def _worker(self, username, category):
        user = CustomUser.objects.create_user(
            username=username, password="x", role="worker"
        )
        return Worker.objects.create(
            user=user, branch=self.branch, worker_category=category
        )

    def _job(self, status="completed", amount=200.0, rate=10.0, workers=()):
        svc = OtherService.objects.create(
            user=self.logger,
            branch=self.branch,
            service_name="Engine steam wash",
            amount=amount,
            commission_rate=rate,
            status=status,
        )
        if workers:
            svc.workers.set(workers)
        return svc

    def test_completed_job_splits_pool_between_providers(self):
        w1 = self._worker("0241111111", self.provider_cat)
        w2 = self._worker("0242222222", self.provider_cat)

        svc = self._job(workers=[w1, w2])

        svc.refresh_from_db()
        self.assertAlmostEqual(svc.commission_amount, 20.0)  # 10% of 200
        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 2)
        for worker in (w1, w2):
            row = Commission.objects.get(other_service=svc, worker=worker)
            self.assertAlmostEqual(row.amount, 10.0)

    def test_non_providers_are_excluded(self):
        provider = self._worker("0241111111", self.provider_cat)
        helper = self._worker("0242222222", self.non_provider_cat)

        svc = self._job(workers=[provider, helper])

        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 1)
        self.assertAlmostEqual(
            Commission.objects.get(other_service=svc).amount, 20.0
        )

    def test_pending_job_earns_nothing_until_completed(self):
        worker = self._worker("0241111111", self.provider_cat)

        svc = self._job(status="pending", workers=[worker])
        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 0)

        svc.mark_completed()
        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 1)

    def test_on_credit_job_earns_like_a_completed_one(self):
        worker = self._worker("0241111111", self.provider_cat)
        svc = self._job(status="onCredit", workers=[worker])
        self.assertAlmostEqual(Commission.objects.get(other_service=svc).amount, 20.0)

    def test_cancelling_a_completed_job_removes_commission(self):
        worker = self._worker("0241111111", self.provider_cat)
        svc = self._job(workers=[worker])
        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 1)

        svc.mark_canceled()

        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 0)
        svc.refresh_from_db()
        self.assertAlmostEqual(svc.commission_amount, 0.0)

    def test_zero_rate_pays_nothing(self):
        worker = self._worker("0241111111", self.provider_cat)
        svc = self._job(rate=0.0, workers=[worker])
        self.assertEqual(Commission.objects.filter(other_service=svc).count(), 0)

    def test_editing_amount_or_rate_resplits_idempotently(self):
        w1 = self._worker("0241111111", self.provider_cat)
        w2 = self._worker("0242222222", self.provider_cat)
        svc = self._job(workers=[w1, w2])

        svc.amount = 400.0
        svc.commission_rate = 20.0
        svc.save()

        rows = Commission.objects.filter(other_service=svc)
        self.assertEqual(rows.count(), 2)  # re-split, not stacked
        for row in rows:
            self.assertAlmostEqual(row.amount, 40.0)  # 20% of 400, halved
        svc.refresh_from_db()
        self.assertAlmostEqual(svc.commission_amount, 80.0)

    def test_dropping_a_worker_removes_only_their_row(self):
        w1 = self._worker("0241111111", self.provider_cat)
        w2 = self._worker("0242222222", self.provider_cat)
        svc = self._job(workers=[w1, w2])

        svc.workers.remove(w2)

        self.assertFalse(Commission.objects.filter(other_service=svc, worker=w2).exists())
        self.assertAlmostEqual(
            Commission.objects.get(other_service=svc, worker=w1).amount, 20.0
        )

    def test_commission_is_visible_to_worker_totals(self):
        """The per-worker aggregation reports use worker+date, not the job link."""
        worker = self._worker("0241111111", self.provider_cat)
        svc = self._job(workers=[worker])

        total = Commission.objects.filter(worker=worker).values_list("amount", flat=True)
        self.assertEqual(list(total), [20.0])
        self.assertEqual(
            Commission.objects.get(other_service=svc).source_name, "Engine steam wash"
        )


class CoreServiceCommissionRegressionTest(TestCase):
    """
    The catalogue path shares its split logic with other services, so guard it
    against changes made for the other-service side.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.category = WorkerCategory.objects.create(
            name="Washer", service_provider=True
        )
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )
        self.service = Service.objects.create(
            service_type="Full wash", price=100.0, commission_rate=10.0
        )

    def _worker(self, username):
        user = CustomUser.objects.create_user(
            username=username, password="x", role="worker"
        )
        return Worker.objects.create(
            user=user, branch=self.branch, worker_category=self.category
        )

    def test_catalogue_line_still_splits_between_providers(self):
        w1 = self._worker("0241111111")
        w2 = self._worker("0242222222")
        order = ServiceRenderedOrder.objects.create(
            user=self.user, branch=self.branch, total_amount=100.0, final_amount=100.0
        )
        sr = ServiceRendered.objects.create(order=order, service=self.service)
        sr.workers.set([w1, w2])

        sr.allocate_commission()

        sr.refresh_from_db()
        self.assertAlmostEqual(sr.commission_amount, 10.0)
        self.assertEqual(Commission.objects.filter(service_rendered=sr).count(), 2)
        for row in Commission.objects.filter(service_rendered=sr):
            self.assertAlmostEqual(row.amount, 5.0)

    def test_discount_factor_scales_the_pool(self):
        worker = self._worker("0241111111")
        order = ServiceRenderedOrder.objects.create(
            user=self.user, branch=self.branch, total_amount=100.0, final_amount=50.0
        )
        sr = ServiceRendered.objects.create(order=order, service=self.service)
        sr.workers.set([worker])

        sr.allocate_commission(discount_factor=0.5)

        self.assertAlmostEqual(
            Commission.objects.get(service_rendered=sr).amount, 5.0
        )

    def test_removing_commission_clears_rows(self):
        worker = self._worker("0241111111")
        order = ServiceRenderedOrder.objects.create(
            user=self.user, branch=self.branch, total_amount=100.0, final_amount=100.0
        )
        sr = ServiceRendered.objects.create(order=order, service=self.service)
        sr.workers.set([worker])
        sr.allocate_commission()

        sr.remove_commission()

        self.assertEqual(Commission.objects.filter(service_rendered=sr).count(), 0)
