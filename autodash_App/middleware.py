# your_app/middleware.py

from django.utils import timezone
from django.core.cache import cache
from .models import RecurringExpense, Expense


class RecurringExpensesMiddleware:
    CACHE_KEY = "recurring_expenses_done_"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        today = timezone.localdate()
        key = f"{self.CACHE_KEY}{today.isoformat()}"
        if not cache.get(key):
            self._mint_for(today)
            cache.set(key, True, 24 * 3600)
        return self.get_response(request)

    def _mint_for(self, today):
        for r in RecurringExpense.objects.all():
            if not r.applies_today(today):
                continue
            if not Expense.objects.filter(
                    branch=r.branch,
                    description=f"[Recurring] {r.description}",
                    amount=r.amount,
                    date=today
            ).exists():
                Expense.objects.create(
                    branch=r.branch,
                    description=f"[Recurring] {r.description}",
                    amount=r.amount,
                    date=today,
                    user=None
                )
