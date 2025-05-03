# middleware.py

from django.utils import timezone
from django.core.cache import cache
from .models import RecurringExpense, Expense


class RecurringExpensesMiddleware:
    """
    Once per day (per Django process), generate any recurring expenses
    for today that haven’t yet been created.
    """
    CACHE_KEY = "recurring_expenses_done_"  # we’ll append date

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        today = timezone.localdate()
        key = f"{self.CACHE_KEY}{today}"
        if not cache.get(key):
            self._mint_recurring(today)
            # mark done for the next 24h
            cache.set(key, True, timeout=60 * 60 * 24)
        return self.get_response(request)

    def _mint_recurring(self, today):
        for r in RecurringExpense.objects.all():
            if not r.applies_today(today):
                continue
            # avoid duplicates
            exists = Expense.objects.filter(
                branch=r.branch,
                description=f"[Recurring] {r.description}",
                amount=r.amount,
                date=today
            ).exists()
            if not exists:
                Expense.objects.create(
                    branch=r.branch,
                    description=f"[Recurring] {r.description}",
                    amount=r.amount,
                    date=today,
                    user=None
                )
