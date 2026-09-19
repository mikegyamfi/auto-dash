"""
What the customer is told they paid.

The completed-order SMS read `cash_paid` alone, so anyone paying by MoMo or
card was texted "GHS 0.00". `total_tendered` covers every tender.
"""
from django.test import TestCase

from autodash_App.models import (
    Branch, Customer, CustomUser, ServiceRenderedOrder,
)


class OrderAmountPaidTest(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="customer", approved=True,
            first_name="Ama", last_name="Mensah", phone_number="0247777777",
        )
        self.customer = Customer.objects.create(user=user, branch=self.branch)
        self.logger = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker", approved=True,
        )

    def _order(self, **tenders):
        return ServiceRenderedOrder.objects.create(
            user=self.logger, customer=self.customer, branch=self.branch,
            total_amount=100.0, final_amount=100.0, status="completed", **tenders,
        )

    def test_cash_only(self):
        self.assertAlmostEqual(self._order(cash_paid=100.0).total_tendered, 100.0)

    def test_momo_only_is_not_zero(self):
        """The live bug: a MoMo customer was told they paid nothing."""
        self.assertAlmostEqual(self._order(momo_amount=100.0).total_tendered, 100.0)

    def test_card_only_is_not_zero(self):
        self.assertAlmostEqual(self._order(card_amount=100.0).total_tendered, 100.0)

    def test_a_split_tender_sums(self):
        order = self._order(cash_paid=40.0, momo_amount=35.0, card_amount=25.0)
        self.assertAlmostEqual(order.total_tendered, 100.0)

    def test_nothing_tendered_is_zero(self):
        self.assertAlmostEqual(self._order().total_tendered, 0.0)

    def test_subscription_and_loyalty_are_not_counted_as_tendered(self):
        """Nothing changed hands for those, so they are not 'paid'."""
        order = self._order(
            cash_paid=10.0, subscription_amount_used=60.0,
            loyalty_points_amount_deduction=30.0,
        )
        self.assertAlmostEqual(order.total_tendered, 10.0)
