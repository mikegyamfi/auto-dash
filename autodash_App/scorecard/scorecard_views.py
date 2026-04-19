"""Views for the employee scorecard module.

Two audiences:
  * Admin (is_staff/superuser) — manages the scorecard structure
    (categories, weights, criteria).
  * GM / branch-admin / superuser — views daily scorecards and adjusts
    individual criteria downward when a worker has faulted. Every worker
    starts each day at full marks by default.
"""
from datetime import datetime, date as date_cls
from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from autodash_App.models import (
    Branch,
    CustomUser,
    DailyScoreEntry,
    DailyScorecard,
    OtherService,
    ScorecardCategory,
    ScorecardCriterion,
    ServiceRenderedOrder,
    Worker,
)


# ---------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------
def _user_is_gm(user) -> bool:
    """GM-group membership, branch-admin flag, staff, or superuser."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.groups.filter(name="GM").exists():
        return True
    wp = getattr(user, "worker_profile", None)
    return bool(wp and wp.is_branch_admin)


def gm_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if _user_is_gm(request.user):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return _wrapped


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _parse_date(raw: str | None) -> date_cls:
    """Parse a YYYY-MM-DD string; fall back to today."""
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return timezone.localdate()


def _visible_branch(request) -> Branch | None:
    """Branch a non-superuser GM is restricted to; None means 'all'."""
    user = request.user
    if user.is_superuser or user.is_staff:
        return None
    wp = getattr(user, "worker_profile", None)
    if wp and wp.branch_id:
        return wp.branch
    return None


def _ensure_scorecard(worker: Worker, on_date: date_cls) -> DailyScorecard:
    """Get (or create) a worker's scorecard for a date, seeding each active
    criterion with full marks on first creation."""
    sc, created = DailyScorecard.objects.get_or_create(
        worker=worker, date=on_date,
        defaults={"branch": worker.branch},
    )
    if created:
        criteria = ScorecardCriterion.objects.filter(active=True, category__active=True)
        DailyScoreEntry.objects.bulk_create([
            DailyScoreEntry(
                scorecard=sc,
                criterion=c,
                points_awarded=c.max_points,
            )
            for c in criteria
        ])
        sc.recalc()
        sc.save(update_fields=["final_score"])
    else:
        # Backfill entries for criteria added after the scorecard was first seeded.
        existing = set(sc.entries.values_list("criterion_id", flat=True))
        new_entries = [
            DailyScoreEntry(scorecard=sc, criterion=c, points_awarded=c.max_points)
            for c in ScorecardCriterion.objects.filter(active=True, category__active=True)
            if c.id not in existing
        ]
        if new_entries:
            DailyScoreEntry.objects.bulk_create(new_entries)
            sc.recalc()
            sc.save(update_fields=["final_score"])
    return sc


# ---------------------------------------------------------------------
# Admin: structure (categories + criteria + weights)
# ---------------------------------------------------------------------
@staff_member_required
@transaction.atomic
def scorecard_structure(request):
    """Single-page CRUD for scorecard categories and criteria."""
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "add_category":
            name = (request.POST.get("name") or "").strip()
            weight_pct = request.POST.get("weight") or "0"
            display_order = request.POST.get("display_order") or "0"
            if not name:
                messages.error(request, "Category name is required.")
            elif ScorecardCategory.objects.filter(name__iexact=name).exists():
                messages.error(request, f"A category named '{name}' already exists.")
            else:
                try:
                    ScorecardCategory.objects.create(
                        name=name,
                        weight=float(weight_pct) / 100.0,
                        display_order=int(display_order),
                    )
                    messages.success(request, f"Added category '{name}'.")
                except (TypeError, ValueError):
                    messages.error(request, "Weight must be a number between 0 and 100.")

        elif action == "update_category":
            cat = get_object_or_404(ScorecardCategory, pk=request.POST.get("category_id"))
            try:
                cat.name = (request.POST.get("name") or cat.name).strip()
                raw_weight = request.POST.get("weight")
                if raw_weight is not None and raw_weight != "":
                    cat.weight = float(raw_weight) / 100.0
                cat.display_order = int(request.POST.get("display_order") or cat.display_order)
                cat.active = request.POST.get("active") == "on"
                cat.full_clean()
                cat.save()
                messages.success(request, f"Updated category '{cat.name}'.")
            except (TypeError, ValueError):
                messages.error(request, "Invalid values for category.")

        elif action == "delete_category":
            cat = get_object_or_404(ScorecardCategory, pk=request.POST.get("category_id"))
            name = cat.name
            cat.delete()
            messages.success(request, f"Deleted category '{name}' and its criteria.")

        elif action == "add_criterion":
            cat = get_object_or_404(ScorecardCategory, pk=request.POST.get("category_id"))
            name = (request.POST.get("name") or "").strip()
            max_points = request.POST.get("max_points") or "100"
            display_order = request.POST.get("display_order") or "0"
            if not name:
                messages.error(request, "Criterion name is required.")
            elif cat.criteria.filter(name__iexact=name).exists():
                messages.error(request, f"'{cat.name}' already has a criterion named '{name}'.")
            else:
                try:
                    ScorecardCriterion.objects.create(
                        category=cat,
                        name=name,
                        max_points=float(max_points),
                        display_order=int(display_order),
                    )
                    messages.success(request, f"Added '{name}' to '{cat.name}'.")
                except (TypeError, ValueError):
                    messages.error(request, "Max points must be a non-negative number.")

        elif action == "update_criterion":
            crit = get_object_or_404(ScorecardCriterion, pk=request.POST.get("criterion_id"))
            try:
                crit.name = (request.POST.get("name") or crit.name).strip()
                crit.max_points = float(request.POST.get("max_points") or crit.max_points)
                crit.display_order = int(request.POST.get("display_order") or crit.display_order)
                crit.active = request.POST.get("active") == "on"
                crit.full_clean()
                crit.save()
                messages.success(request, f"Updated criterion '{crit.name}'.")
            except (TypeError, ValueError):
                messages.error(request, "Invalid values for criterion.")

        elif action == "delete_criterion":
            crit = get_object_or_404(ScorecardCriterion, pk=request.POST.get("criterion_id"))
            name = crit.name
            crit.delete()
            messages.success(request, f"Deleted criterion '{name}'.")

        else:
            messages.error(request, "Unknown action.")

        return redirect("scorecard_structure")

    categories = (
        ScorecardCategory.objects
        .prefetch_related("criteria")
        .all()
    )
    weight_sum = sum(c.weight for c in categories if c.active)
    return render(request, "layouts/admin/scorecard_structure.html", {
        "categories": categories,
        "weight_sum": weight_sum,
        "weight_balanced": abs(weight_sum - 1.0) < 0.0001,
    })


# ---------------------------------------------------------------------
# GM: daily list of workers with their scorecard status
# ---------------------------------------------------------------------
@gm_required
def daily_scorecards(request):
    user = request.user
    forced_branch = _visible_branch(request)

    on_date = _parse_date(request.GET.get("date"))

    # Branch filter: forced for branch-admins; free for staff/superuser.
    if forced_branch:
        selected_branch = forced_branch
    else:
        b_id = request.GET.get("branch")
        selected_branch = Branch.objects.filter(pk=b_id).first() if b_id else None

    workers_qs = (
        Worker.objects
        .select_related("user", "branch", "worker_category")
        .order_by("user__first_name", "user__last_name")
    )
    if selected_branch:
        workers_qs = workers_qs.filter(branch=selected_branch)

    # Only show workers who actually did work on this date — either rendered
    # a service order or an "other service" — plus anyone already scored for
    # the day (so saved cards don't disappear if their work is later undone).
    worked_ids = set(
        ServiceRenderedOrder.objects
        .filter(date__date=on_date)
        .values_list("workers__id", flat=True)
    )
    worked_ids.update(
        OtherService.objects
        .filter(created_at__date=on_date)
        .values_list("workers__id", flat=True)
    )
    worked_ids.discard(None)

    already_scored_ids = set(
        DailyScorecard.objects
        .filter(date=on_date)
        .values_list("worker_id", flat=True)
    )
    visible_ids = worked_ids | already_scored_ids
    workers_qs = workers_qs.filter(id__in=visible_ids)

    # Existing scorecards for this date keyed by worker id (don't auto-create
    # on the list view — creation happens when a GM opens a worker to score).
    existing = {
        sc.worker_id: sc
        for sc in DailyScorecard.objects
            .filter(date=on_date, worker__in=workers_qs)
            .only("id", "worker_id", "final_score", "updated_at")
    }

    rows = []
    for w in workers_qs:
        sc = existing.get(w.id)
        rows.append({
            "worker": w,
            "scorecard": sc,
            "final_score": sc.final_score if sc else 1.0,
            "status": "Scored" if sc else "Default (100%)",
            "updated_at": sc.updated_at if sc else None,
        })

    branches = Branch.objects.all() if not forced_branch else None

    return render(request, "layouts/admin/daily_scorecards.html", {
        "rows": rows,
        "on_date": on_date,
        "branches": branches,
        "selected_branch": selected_branch,
        "hide_branch_selector": bool(forced_branch),
    })


# ---------------------------------------------------------------------
# GM: score a single worker for a specific date
# ---------------------------------------------------------------------
@gm_required
@transaction.atomic
def score_worker(request, worker_id):
    worker = get_object_or_404(
        Worker.objects.select_related("user", "branch"),
        pk=worker_id,
    )

    # Branch-scoped access check.
    forced_branch = _visible_branch(request)
    if forced_branch and worker.branch_id != forced_branch.id:
        return HttpResponseForbidden("You may only score workers in your branch.")

    on_date = _parse_date(request.GET.get("date") or request.POST.get("date"))
    scorecard = _ensure_scorecard(worker, on_date)

    entries = (
        scorecard.entries
        .select_related("criterion", "criterion__category")
        .all()
    )

    if request.method == "POST":
        entry_map = {e.id: e for e in entries}
        for entry_id, entry in entry_map.items():
            raw = request.POST.get(f"points_{entry_id}")
            reason = (request.POST.get(f"reason_{entry_id}") or "").strip()
            if raw is None:
                continue
            try:
                new_points = float(raw)
            except (TypeError, ValueError):
                messages.error(
                    request,
                    f"Invalid points for {entry.criterion.name}; left unchanged.",
                )
                continue

            # Clamp to [0, max_points] so you can't over-award.
            new_points = max(0.0, min(new_points, entry.criterion.max_points))

            if (
                new_points != entry.points_awarded
                or reason != entry.reason
            ):
                entry.points_awarded = new_points
                entry.reason = reason
                entry.adjusted_by = request.user if request.user.is_authenticated else None
                entry.save()

        scorecard.notes = (request.POST.get("notes") or "").strip()
        scorecard.recalc()
        scorecard.save()
        messages.success(
            request,
            f"Saved scorecard for {worker.user.get_full_name()} "
            f"on {on_date:%Y-%m-%d} — final score {scorecard.final_score:.0%}.",
        )
        return redirect(f"{request.path}?date={on_date:%Y-%m-%d}")

    # Group entries by category for the template.
    grouped: dict[int, dict] = {}
    for e in entries:
        cat = e.criterion.category
        bucket = grouped.setdefault(cat.id, {
            "category": cat,
            "entries": [],
            "awarded": 0.0,
            "max": 0.0,
        })
        bucket["entries"].append(e)
        bucket["awarded"] += e.points_awarded or 0.0
        bucket["max"] += e.criterion.max_points or 0.0

    # Stable order by category.display_order.
    grouped_list = sorted(grouped.values(), key=lambda g: g["category"].display_order)
    for g in grouped_list:
        g["pct"] = (g["awarded"] / g["max"]) if g["max"] else 0.0
        g["weighted"] = g["pct"] * g["category"].weight

    return render(request, "layouts/admin/score_worker.html", {
        "worker": worker,
        "scorecard": scorecard,
        "on_date": on_date,
        "grouped": grouped_list,
    })