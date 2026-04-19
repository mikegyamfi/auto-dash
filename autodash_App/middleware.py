from django.utils import timezone
from django.core.cache import cache
from .models import RecurringPaymentSetup, DailyPaymentTarget


class DailyTargetGenerationMiddleware:
    """
    Middleware that acts as a daily trigger. 
    The first time any user loads a page on a new day, it generates the daily payment targets.
    """
    CACHE_KEY = "daily_payment_targets_done_"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        today = timezone.localdate()
        key = f"{self.CACHE_KEY}{today.isoformat()}"

        # If today's targets haven't been generated yet, do it now.
        if not cache.get(key):
            self._generate_targets_for(today)
            # Cache it for 24 hours so it doesn't run again today
            cache.set(key, True, 24 * 3600)

        return self.get_response(request)

    def _generate_targets_for(self, today):
        setups = RecurringPaymentSetup.objects.all()

        for setup in setups:
            if setup.applies_today(today):
                # 1. Prevent duplicate generation for the same day (safety check)
                if DailyPaymentTarget.objects.filter(setup=setup, date=today).exists():
                    continue

                # 2. Find the most recent target before today to check for unpaid debt
                last_target = DailyPaymentTarget.objects.filter(
                    setup=setup,
                    date__lt=today
                ).order_by('-date').first()

                brought_forward = 0.0
                if last_target:
                    # By allowing negative numbers, an overpayment becomes a credit for tomorrow!
                    brought_forward = last_target.total_target - last_target.amount_paid

                # 3. Create today's new target with the carried-over debt
                DailyPaymentTarget.objects.create(
                    setup=setup,
                    date=today,
                    branch=setup.branch,
                    base_amount=setup.base_amount,
                    brought_forward=brought_forward
                    # total_target and is_settled are handled automatically by the model's save() method
                )



