from django.test import TestCase
from django.utils import timezone
from django.db.models import Sum
from autodash_App.models import ServiceRenderedOrder, Revenue


class RevenueConsistencyTest(TestCase):
    fixtures = []  # add fixtures if you have them

    def test_revenue_matches_orders_today(self):
        today = timezone.localdate()
        srv_tot = (ServiceRenderedOrder.objects
                   .filter(date__date=today,
                           status__in=["completed", "onCredit"])
                   .aggregate(Sum("final_amount"))["final_amount__sum"] or 0)
        rev_tot = (Revenue.objects
                   .filter(timestamp__date=today)
                   .aggregate(Sum("final_amount"))["final_amount__sum"] or 0)
        self.assertEqual(
            srv_tot, rev_tot,
            f"Revenue mismatch on {today}: orders={srv_tot}, revenue={rev_tot}"
        )
