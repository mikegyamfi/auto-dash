from decimal import Decimal

from django.test import TestCase

from autodash_App.commission_util import DEC2, compute_pool, split_pool
from autodash_App.models import (
    Branch, Commission, CustomUser, Service, ServiceRendered,
    ServiceRenderedOrder, Worker, WorkerCategory,
)


class SplitPoolTest(TestCase):
    """The split must never lose or invent money."""

    def test_shares_always_sum_to_the_pool(self):
        # The exhaustive version of "3 x 3.33 != 10.00".
        for cents in range(0, 5000, 7):
            pool = Decimal(cents) / 100
            for n in range(1, 13):
                shares = split_pool(pool, n)
                self.assertEqual(
                    sum(shares), DEC2(pool),
                    f"{pool} across {n} workers summed to {sum(shares)}",
                )
                self.assertEqual(len(shares), n)

    def test_leftover_cents_go_to_the_earliest_shares(self):
        self.assertEqual(
            split_pool(Decimal("10.00"), 3),
            [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")],
        )

    def test_even_split_is_exact(self):
        self.assertEqual(
            split_pool(Decimal("10.00"), 2), [Decimal("5.00"), Decimal("5.00")]
        )

    def test_no_workers_yields_no_shares(self):
        self.assertEqual(split_pool(Decimal("10.00"), 0), [])

    def test_shares_never_differ_by_more_than_a_cent(self):
        for n in range(1, 10):
            shares = split_pool(Decimal("100.00"), n)
            self.assertLessEqual(max(shares) - min(shares), Decimal("0.01"))


class ComputePoolTest(TestCase):
    def test_rate_is_a_percentage_of_price(self):
        self.assertEqual(compute_pool(100, 30), Decimal("30.00"))
        self.assertEqual(compute_pool(1270, 3), Decimal("38.10"))

    def test_zero_or_missing_rate_pays_nothing(self):
        self.assertEqual(compute_pool(100, 0), Decimal("0.00"))
        self.assertEqual(compute_pool(100, None), Decimal("0.00"))

    def test_discount_factor_scales_the_pool(self):
        self.assertEqual(compute_pool(100, 30, 0.5), Decimal("15.00"))

    def test_float_rates_do_not_pick_up_binary_noise(self):
        # Decimal(0.1) is 0.1000000000000000055511151231257827; str() avoids it.
        self.assertEqual(compute_pool(1000, 0.1), Decimal("1.00"))
        self.assertEqual(compute_pool(200, 2.5), Decimal("5.00"))


class CommissionIntegrityTest(TestCase):
    """End-to-end: the cache and the rows must always agree."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch", location="Accra", phone_number="0240000000"
        )
        self.category = WorkerCategory.objects.create(name="Washer", service_provider=True)
        self.user = CustomUser.objects.create_user(
            username="0249999999", password="x", role="worker"
        )
        self.service = Service.objects.create(
            service_type="Full wash", price=100.0, commission_rate=10.0
        )

    def _worker(self, username):
        user = CustomUser.objects.create_user(username=username, password="x", role="worker")
        return Worker.objects.create(
            user=user, branch=self.branch, worker_category=self.category
        )

    def _line(self, workers, price=100.0):
        order = ServiceRenderedOrder.objects.create(
            user=self.user, branch=self.branch, total_amount=price, final_amount=price
        )
        sr = ServiceRendered.objects.create(
            order=order, service=self.service, negotiated_price=price
        )
        sr.workers.set(workers)
        return sr

    def test_cached_total_equals_the_sum_of_rows(self):
        for n in range(1, 6):
            workers = [self._worker(f"024000{n}{i}") for i in range(n)]
            sr = self._line(workers)
            sr.allocate_commission()
            sr.refresh_from_db()

            rows_total = sum(c.amount for c in sr.commissions.all())
            self.assertAlmostEqual(
                rows_total, sr.commission_amount, places=2,
                msg=f"{n} workers: rows={rows_total} cache={sr.commission_amount}",
            )

    def test_three_way_split_loses_no_pesewa(self):
        workers = [self._worker(f"02411111{i}") for i in range(3)]
        sr = self._line(workers)
        sr.allocate_commission()
        sr.refresh_from_db()

        amounts = sorted(c.amount for c in sr.commissions.all())
        self.assertEqual(amounts, [3.33, 3.33, 3.34])
        self.assertAlmostEqual(sr.commission_amount, 10.0)

    def test_a_line_with_no_workers_caches_no_commission(self):
        """The old code guessed a commission here that nothing backed."""
        sr = self._line([])
        sr.refresh_from_db()
        self.assertEqual(sr.commission_amount, 0.0)
        self.assertEqual(sr.commissions.count(), 0)

    def test_unallocated_line_caches_no_commission(self):
        worker = self._worker("0241111111")
        sr = self._line([worker])  # never allocated
        sr.refresh_from_db()
        self.assertEqual(sr.commission_amount, 0.0)

    def test_commission_is_dated_to_the_job_not_to_allocation(self):
        worker = self._worker("0241111111")
        sr = self._line([worker])
        sr.allocate_commission()

        order_date = sr.order.date.date()
        self.assertEqual(Commission.objects.get(service_rendered=sr).date, order_date)

        # Re-allocating later must not drag the row into today.
        sr.allocate_commission()
        self.assertEqual(Commission.objects.get(service_rendered=sr).date, order_date)

    def test_reallocation_is_idempotent(self):
        workers = [self._worker(f"02422222{i}") for i in range(3)]
        sr = self._line(workers)

        for _ in range(4):
            sr.allocate_commission()

        self.assertEqual(sr.commissions.count(), 3)
        sr.refresh_from_db()
        self.assertAlmostEqual(
            sum(c.amount for c in sr.commissions.all()), sr.commission_amount, places=2
        )

    def test_rate_change_is_picked_up_on_reallocation(self):
        """Changing the rate and re-running must restate the line exactly."""
        worker = self._worker("0241111111")
        sr = self._line([worker])
        sr.allocate_commission()
        self.assertAlmostEqual(Commission.objects.get(service_rendered=sr).amount, 10.0)

        self.service.commission_rate = 30.0
        self.service.save()
        sr.allocate_commission()

        self.assertAlmostEqual(Commission.objects.get(service_rendered=sr).amount, 30.0)
        sr.refresh_from_db()
        self.assertAlmostEqual(sr.commission_amount, 30.0)
