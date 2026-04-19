"""Views for the employee scorecard module.

Two audiences:
  * Admin (is_staff/superuser) — manages the scorecard structure
    (categories, weights, criteria).
  * GM / branch-admin / superuser — views daily scorecards and adjusts
    individual criteria downward when a worker has faulted. Every worker
    starts each day at full marks by default.
"""
import json
from datetime import datetime, date as date_cls, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count, Max, Min
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


def _count_orders_for(worker: Worker, on_date: date_cls) -> int:
    """Number of service orders this worker participated in on the given date."""
    return (
        ServiceRenderedOrder.objects
        .filter(workers=worker, date__date=on_date)
        .distinct()
        .count()
    )


def _count_services_for(worker: Worker, on_date: date_cls) -> int:
    """Number of individual services rendered by this worker on the date,
    combining core `ServiceRendered` and ad-hoc `OtherService`."""
    from autodash_App.models import ServiceRendered
    core = ServiceRendered.objects.filter(
        workers=worker, date__date=on_date
    ).count()
    other = OtherService.objects.filter(
        workers=worker, created_at__date=on_date
    ).count()
    return core + other


def _auto_points(criterion: ScorecardCriterion, worker: Worker, on_date: date_cls) -> float:
    """Compute points for an auto-scored criterion based on actual vs target.

    Returns a value in [0, max_points]. If target is 0 (not set), awards full
    marks — can't measure, so don't penalise the worker.
    """
    if criterion.auto_source == ScorecardCriterion.AUTO_SOURCE_ORDERS:
        actual = _count_orders_for(worker, on_date)
        target = worker.daily_orders_target or 0
    elif criterion.auto_source == ScorecardCriterion.AUTO_SOURCE_SERVICES:
        actual = _count_services_for(worker, on_date)
        target = worker.daily_services_target or 0
    else:
        return criterion.max_points

    if target <= 0:
        return criterion.max_points  # no target set → treat as 100%
    ratio = min(1.0, actual / target)
    return round(ratio * criterion.max_points, 2)


def _initial_points(criterion: ScorecardCriterion, worker: Worker, on_date: date_cls) -> float:
    """Initial points when first seeding an entry. Auto criteria get computed;
    manual criteria start at full marks."""
    if criterion.is_auto:
        return _auto_points(criterion, worker, on_date)
    return criterion.max_points


def _ensure_scorecard(worker: Worker, on_date: date_cls) -> DailyScorecard:
    """Get (or create) a worker's scorecard for a date, seeding each active
    criterion. Manual criteria start at full marks; auto criteria are computed.
    Auto criteria are also refreshed on every access to stay current."""
    sc, created = DailyScorecard.objects.get_or_create(
        worker=worker, date=on_date,
        defaults={"branch": worker.branch},
    )
    active_criteria = list(
        ScorecardCriterion.objects.filter(active=True, category__active=True)
    )

    if created:
        DailyScoreEntry.objects.bulk_create([
            DailyScoreEntry(
                scorecard=sc,
                criterion=c,
                points_awarded=_initial_points(c, worker, on_date),
            )
            for c in active_criteria
        ])
    else:
        # Backfill entries for criteria added after the scorecard was first seeded.
        existing = set(sc.entries.values_list("criterion_id", flat=True))
        new_entries = [
            DailyScoreEntry(
                scorecard=sc, criterion=c,
                points_awarded=_initial_points(c, worker, on_date),
            )
            for c in active_criteria if c.id not in existing
        ]
        if new_entries:
            DailyScoreEntry.objects.bulk_create(new_entries)

    # Refresh auto-scored entries every time so the UI reflects current work.
    auto_entries = sc.entries.select_related("criterion").filter(
        criterion__auto_source__in=[
            ScorecardCriterion.AUTO_SOURCE_ORDERS,
            ScorecardCriterion.AUTO_SOURCE_SERVICES,
        ]
    )
    for entry in auto_entries:
        new_val = _auto_points(entry.criterion, worker, on_date)
        if entry.points_awarded != new_val:
            entry.points_awarded = new_val
            entry.save(update_fields=["points_awarded", "updated_at"])

    sc.recalc()
    sc.save(update_fields=["final_score"])
    return sc


# ---------------------------------------------------------------------
# Admin: per-worker productivity targets
# ---------------------------------------------------------------------
@gm_required
def scorecard_targets(request):
    """List workers with editable daily order/service targets. Branch-scoped
    for branch-admins; staff/superuser see all with an optional branch filter."""
    forced_branch = _visible_branch(request)
    if forced_branch:
        selected_branch = forced_branch
    else:
        b_id = request.GET.get("branch")
        selected_branch = Branch.objects.filter(pk=b_id).first() if b_id else None

    workers_qs = (
        Worker.objects
        .select_related("user", "branch")
        .order_by("branch__name", "user__first_name", "user__last_name")
    )
    if selected_branch:
        workers_qs = workers_qs.filter(branch=selected_branch)

    if request.method == "POST":
        updated = 0
        for worker in workers_qs:
            raw_orders = request.POST.get(f"orders_{worker.id}")
            raw_services = request.POST.get(f"services_{worker.id}")
            if raw_orders is None and raw_services is None:
                continue
            try:
                new_orders = float(raw_orders) if raw_orders not in (None, "") else worker.daily_orders_target
                new_services = float(raw_services) if raw_services not in (None, "") else worker.daily_services_target
            except (TypeError, ValueError):
                continue
            if (new_orders != worker.daily_orders_target
                    or new_services != worker.daily_services_target):
                worker.daily_orders_target = max(0.0, new_orders)
                worker.daily_services_target = max(0.0, new_services)
                worker.save(update_fields=["daily_orders_target", "daily_services_target"])
                updated += 1
        messages.success(request, f"Updated targets for {updated} worker(s).")
        qs = f"?branch={selected_branch.id}" if selected_branch else ""
        return redirect(f"{request.path}{qs}")

    return render(request, "layouts/admin/scorecard_targets.html", {
        "workers": workers_qs,
        "branches": Branch.objects.all() if not forced_branch else None,
        "selected_branch": selected_branch,
        "hide_branch_selector": bool(forced_branch),
    })


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
            # Auto-scored criteria ignore user input — values come from
            # real work counts via _ensure_scorecard refresh.
            if entry.criterion.is_auto:
                continue

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

        # Refresh auto-scored entries again in case work was logged between
        # opening the page and pressing save. This also recalculates final_score.
        scorecard = _ensure_scorecard(worker, on_date)
        scorecard.notes = (request.POST.get("notes") or "").strip()
        scorecard.save(update_fields=["notes"])
        messages.success(
            request,
            f"Saved scorecard for {worker.user.get_full_name()} "
            f"on {on_date:%Y-%m-%d} — final score {scorecard.final_score:.0%}.",
        )
        return redirect(f"{request.path}?date={on_date:%Y-%m-%d}")

    # Re-fetch entries post-refresh so auto values are current.
    entries = (
        scorecard.entries
        .select_related("criterion", "criterion__category")
        .all()
    )

    # Build per-entry context (auto criteria include actual/target breakdown).
    grouped: dict[int, dict] = {}
    for e in entries:
        cat = e.criterion.category
        bucket = grouped.setdefault(cat.id, {
            "category": cat,
            "entries": [],
            "awarded": 0.0,
            "max": 0.0,
        })
        row = {"entry": e}
        if e.criterion.auto_source == ScorecardCriterion.AUTO_SOURCE_ORDERS:
            row["actual"] = _count_orders_for(worker, on_date)
            row["target"] = worker.daily_orders_target
            row["auto_label"] = "Orders done"
        elif e.criterion.auto_source == ScorecardCriterion.AUTO_SOURCE_SERVICES:
            row["actual"] = _count_services_for(worker, on_date)
            row["target"] = worker.daily_services_target
            row["auto_label"] = "Services done"
        else:
            row["actual"] = None
            row["target"] = None
        bucket["entries"].append(row)
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


# ---------------------------------------------------------------------
# Reports: performance over a period
# ---------------------------------------------------------------------
@gm_required
def scorecard_report(request):
    """Aggregate scorecard performance over a date range.

    Filters: branch (staff/superuser only), date range, optional worker.
    Produces:
      * Summary cards (total workers, avg score, best/worst performer)
      * Daily team-average trend (line chart)
      * Performance distribution (doughnut)
      * Top performers ranked (bar)
      * Per-worker detail table
    """
    forced_branch = _visible_branch(request)
    if forced_branch:
        selected_branch = forced_branch
    else:
        b_id = request.GET.get("branch")
        selected_branch = Branch.objects.filter(pk=b_id).first() if b_id else None

    today = timezone.localdate()
    start_date = _parse_date(request.GET.get("start_date")) if request.GET.get("start_date") else today - timedelta(days=13)
    end_date = _parse_date(request.GET.get("end_date")) if request.GET.get("end_date") else today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    worker_id = request.GET.get("worker")
    selected_worker = Worker.objects.filter(pk=worker_id).first() if worker_id else None

    # Base queryset: all scorecards in the period scoped to branch.
    sc_qs = (
        DailyScorecard.objects
        .filter(date__gte=start_date, date__lte=end_date)
        .select_related("worker", "worker__user", "worker__branch")
    )
    if selected_branch:
        sc_qs = sc_qs.filter(branch=selected_branch)
    if selected_worker:
        sc_qs = sc_qs.filter(worker=selected_worker)

    total_scorecards = sc_qs.count()

    # --- Per-worker summary ---
    per_worker = list(
        sc_qs.values(
            "worker_id",
            "worker__user__first_name",
            "worker__user__last_name",
            "worker__user__username",
            "worker__branch__name",
            "worker__position",
        )
        .annotate(
            days_scored=Count("id"),
            avg_score=Avg("final_score"),
            best_score=Max("final_score"),
            worst_score=Min("final_score"),
        )
        .order_by("-avg_score")
    )

    for row in per_worker:
        full = f"{row['worker__user__first_name'] or ''} {row['worker__user__last_name'] or ''}".strip()
        row["name"] = full or row["worker__user__username"] or "Worker"
        row["avg_pct"] = round((row["avg_score"] or 0) * 100, 1)
        row["best_pct"] = round((row["best_score"] or 0) * 100, 1)
        row["worst_pct"] = round((row["worst_score"] or 0) * 100, 1)

    # --- Summary cards ---
    total_workers = len(per_worker)
    team_avg = sum(r["avg_score"] or 0 for r in per_worker) / total_workers if total_workers else 0
    best = per_worker[0] if per_worker else None
    worst = per_worker[-1] if per_worker else None

    # --- Daily trend (team average per date) ---
    all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    per_day = {
        row["date"]: row["avg"]
        for row in sc_qs.values("date").annotate(avg=Avg("final_score"))
    }
    trend_labels = [d.strftime("%b %d") for d in all_dates]
    trend_values = [round((per_day.get(d) or 0) * 100, 1) for d in all_dates]

    # --- Distribution buckets by per-worker avg ---
    buckets = {"Excellent (80%+)": 0, "Good (50–80%)": 0, "Needs Work (<50%)": 0}
    for row in per_worker:
        avg = row["avg_score"] or 0
        if avg >= 0.8:
            buckets["Excellent (80%+)"] += 1
        elif avg >= 0.5:
            buckets["Good (50–80%)"] += 1
        else:
            buckets["Needs Work (<50%)"] += 1

    # --- Top N ranking (limit to 10 for chart readability) ---
    top_ranked = per_worker[:10]
    rank_labels = [r["name"] for r in top_ranked]
    rank_values = [r["avg_pct"] for r in top_ranked]

    # Workers list for filter dropdown.
    workers_for_filter_qs = Worker.objects.select_related("user", "branch").order_by("user__first_name")
    if forced_branch:
        workers_for_filter_qs = workers_for_filter_qs.filter(branch=forced_branch)
    elif selected_branch:
        workers_for_filter_qs = workers_for_filter_qs.filter(branch=selected_branch)

    # --- Worker drill-down matrix (dates × criteria) ---
    matrix_categories = []
    matrix_criteria = []
    worker_matrix = []
    matrix_averages = []
    if selected_worker:
        matrix_criteria = list(
            ScorecardCriterion.objects
            .filter(active=True, category__active=True)
            .select_related("category")
            .order_by("category__display_order", "display_order", "name")
        )

        # Group for the header spans.
        grouped_by_cat = {}
        for c in matrix_criteria:
            grouped_by_cat.setdefault(c.category_id, {
                "category": c.category, "criteria": [],
            })["criteria"].append(c)
        matrix_categories = sorted(
            grouped_by_cat.values(),
            key=lambda g: g["category"].display_order,
        )

        cards = (
            DailyScorecard.objects
            .filter(worker=selected_worker, date__gte=start_date, date__lte=end_date)
            .order_by("-date")
            .prefetch_related("entries__criterion")
        )

        criterion_totals = {c.id: {"sum": 0.0, "count": 0} for c in matrix_criteria}

        for card in cards:
            entries_by_crit = {e.criterion_id: e for e in card.entries.all()}
            cells = []
            for c in matrix_criteria:
                e = entries_by_crit.get(c.id)
                if e is None:
                    cells.append(None)
                    continue
                max_pts = c.max_points or 1
                pct = (e.points_awarded or 0) / max_pts
                cells.append({
                    "awarded": e.points_awarded or 0,
                    "max": c.max_points,
                    "pct": pct,
                    "pct_display": round(pct * 100),
                    "reason": e.reason,
                })
                criterion_totals[c.id]["sum"] += e.points_awarded or 0
                criterion_totals[c.id]["count"] += 1

            worker_matrix.append({
                "date": card.date,
                "final_score": card.final_score,
                "final_pct": round((card.final_score or 0) * 100),
                "cells": cells,
            })

        for c in matrix_criteria:
            t = criterion_totals[c.id]
            avg = (t["sum"] / t["count"]) if t["count"] else 0
            max_pts = c.max_points or 1
            pct = avg / max_pts
            matrix_averages.append({
                "criterion": c,
                "avg": round(avg, 1),
                "pct_display": round(pct * 100),
            })

    return render(request, "layouts/admin/scorecard_report.html", {
        "start_date": start_date,
        "end_date": end_date,
        "branches": Branch.objects.all() if not forced_branch else None,
        "selected_branch": selected_branch,
        "hide_branch_selector": bool(forced_branch),
        "workers_for_filter": workers_for_filter_qs,
        "selected_worker": selected_worker,

        # headline stats
        "total_scorecards": total_scorecards,
        "total_workers": total_workers,
        "team_avg": team_avg,
        "team_avg_pct": round(team_avg * 100, 1),
        "best_performer": best,
        "worst_performer": worst,

        # per-worker table
        "per_worker": per_worker,

        # chart data (JSON-serialised for <script>)
        "trend_labels_json": json.dumps(trend_labels),
        "trend_values_json": json.dumps(trend_values),
        "dist_labels_json": json.dumps(list(buckets.keys())),
        "dist_values_json": json.dumps(list(buckets.values())),
        "rank_labels_json": json.dumps(rank_labels),
        "rank_values_json": json.dumps(rank_values),

        # worker drill-down matrix
        "matrix_categories": matrix_categories,
        "matrix_criteria": matrix_criteria,
        "worker_matrix": worker_matrix,
        "matrix_averages": matrix_averages,
    })