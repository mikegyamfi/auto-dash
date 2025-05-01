# commission_utils.py
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone


DEC2 = lambda x: Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def allocate_commission(service_rendered, *, discount_factor=1):
    from .models import Commission, Worker
    """
    Idempotently (re-)distributes commission for one ServiceRendered row.

    • All workers on the service whose category is service_provider=True
      get an equal share of the pool.
    • If the pool is zero OR no providers, existing Commission rows are deleted.
    """
    sr = service_rendered
    effective_price = DEC2(sr.get_effective_price()) * Decimal(str(discount_factor))
    pool = DEC2(effective_price * Decimal(sr.service.commission_rate) / 100) \
        if sr.service.commission_rate else Decimal("0")

    providers = sr.workers.filter(worker_category__service_provider=True)

    with transaction.atomic():
        # Wipe obsolete rows first
        Commission.objects.filter(service_rendered=sr).exclude(worker__in=providers).delete()

        if not providers.exists() or pool == 0:
            Commission.objects.filter(service_rendered=sr).delete()
            sr.commission_amount = Decimal("0")
            sr.save(update_fields=["commission_amount"])
            return

        per_worker = DEC2(pool / providers.count())

        for worker in providers:
            Commission.objects.update_or_create(
                worker=worker,
                service_rendered=sr,
                defaults={"amount": per_worker, "date": timezone.now().date()},
            )

        sr.commission_amount = pool
        sr.save(update_fields=["commission_amount"])
