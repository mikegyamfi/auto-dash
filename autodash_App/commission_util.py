# commission_utils.py
"""
The commission split, in one place.

Rules the rest of the system relies on:

  pool  = effective_price x discount_factor x (rate / 100)
  share = pool / (number of eligible workers on the job)

and three guarantees this module is responsible for:

  1. The per-worker shares always sum to EXACTLY the pool. Dividing by three
     leaves a pesewa over; it is handed out rather than silently dropped, so
     `sum(Commission.amount) == job.commission_amount` always holds.
  2. The cached `commission_amount` never claims money that has no Commission
     row behind it.
  3. Re-running allocation is idempotent and does not move a commission's date;
     the date follows the job, not the moment the row happened to be written.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

CENT = Decimal("0.01")


def DEC2(x):
    """Round to 2dp, half up. Accepts float/int/str/Decimal."""
    return _dec(x).quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(x):
    """
    Decimal from anything, without binary float noise: a float goes through
    str() so 0.1 stays 0.1 rather than 0.10000000000000000555...
    """
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x or 0))


def split_pool(pool, n):
    """
    Split `pool` into `n` shares that sum to exactly `pool`.

    Each share is the floor to the cent; the leftover cents go one each to the
    earliest shares. 10.00 across 3 becomes 3.34 + 3.33 + 3.33, not 3 x 3.33
    (which loses a pesewa). Returns [] for n <= 0.
    """
    if n <= 0:
        return []
    pool = DEC2(pool)
    base = (pool / n).quantize(CENT, rounding="ROUND_DOWN")
    shares = [base] * n
    # Whatever the flooring left behind, in whole cents.
    leftover = int(((pool - base * n) / CENT).to_integral_value())
    for i in range(leftover):
        shares[i] += CENT
    return shares


def compute_pool(effective_price, rate, discount_factor=1):
    """The commission pot for one job, before it is split."""
    rate = _dec(rate)
    if rate <= 0:
        return Decimal("0.00")
    price = DEC2(effective_price) * _dec(discount_factor)
    return DEC2(price * rate / 100)


def _distribute(job, *, link_field, pool, providers, job_date):
    """
    Shared split: `pool` shared equally between the eligible workers on `job`,
    written as Commission rows linked through `link_field`.

    Idempotent — re-running wipes rows for workers no longer on the job, and a
    zero pool or no providers clears the lot. `job.commission_amount` is only
    ever set to the total actually written out.
    """
    from .models import Commission

    link = {link_field: job}

    with transaction.atomic():
        # Wipe rows for anyone no longer on the job.
        Commission.objects.filter(**link).exclude(worker__in=providers).delete()

        workers = list(providers.order_by("id"))
        if not workers or pool <= 0:
            Commission.objects.filter(**link).delete()
            _set_commission_amount(job, Decimal("0.00"))
            return

        shares = split_pool(pool, len(workers))

        for worker, share in zip(workers, shares):
            Commission.objects.update_or_create(
                worker=worker,
                defaults={"amount": float(share), "date": job_date},
                **link,
            )

        # The cache records what was actually written, so it can never claim
        # money with no Commission row behind it.
        _set_commission_amount(job, sum(shares))


def _set_commission_amount(job, amount):
    """
    Persist the cached pool without re-triggering the job's own save() — an
    OtherService save fires the signal that called us, so a plain .save() here
    would recurse.
    """
    job.commission_amount = float(amount)
    type(job).objects.filter(pk=job.pk).update(commission_amount=float(amount))


def _service_rendered_date(sr):
    """
    The day the work happened. Falls back to the line's own timestamp when it
    has no order, so a commission always has a date tied to the job rather than
    to whenever allocation last ran.
    """
    order = sr.order if sr.order_id else None
    if order is not None and order.date:
        return order.date.date()
    return sr.date.date() if sr.date else None


def allocate_commission(service_rendered, *, discount_factor=1):
    """
    Idempotently (re-)distributes commission for one ServiceRendered row.

    • All workers on the service whose category is service_provider=True
      get an equal share of the pool.
    • If the pool is zero OR no providers, existing Commission rows are deleted.
    """
    sr = service_rendered
    pool = compute_pool(
        sr.get_effective_price(),
        sr.service.commission_rate if sr.service_id else 0,
        discount_factor,
    )
    _distribute(
        sr,
        link_field="service_rendered",
        pool=pool,
        providers=sr.workers.filter(worker_category__service_provider=True),
        job_date=_service_rendered_date(sr),
    )


def allocate_other_service_commission(other_service, *, discount_factor=1):
    """
    Same split for a non-catalogue job. The rate lives on the OtherService row
    itself (there's no Service to inherit one from), and defaults to 0 — so a
    job only pays commission once someone sets a rate on it.
    """
    svc = other_service
    pool = compute_pool(svc.get_effective_price(), svc.commission_rate, discount_factor)
    _distribute(
        svc,
        link_field="other_service",
        pool=pool,
        providers=svc.workers.filter(worker_category__service_provider=True),
        job_date=svc.created_at.date() if svc.created_at else None,
    )
