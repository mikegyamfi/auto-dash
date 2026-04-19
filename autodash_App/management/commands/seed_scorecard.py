"""Seed the scorecard structure from the APPLICATION FORM Scorecard sheet.

Usage:
    python manage.py seed_scorecard           # upsert (safe to re-run)
    python manage.py seed_scorecard --reset   # wipe + reseed (drops existing scorecards!)
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from autodash_App.models import (
    ScorecardCategory,
    ScorecardCriterion,
    DailyScorecard,
    DailyScoreEntry,
)


# Structure mirrored from APPLICATION FORM.xlsx → "Scorecard" sheet.
#   Category weights (row 1): 0.40 / 0.15 / 0.15 / 0.15 / 0.15  (sum = 1.00)
#   Criterion max_points keep the raw full-mark values used in the sheet so
#   the within-category weighting is preserved.
SCORECARD_STRUCTURE = [
    {
        "name": "Productivity",
        "weight": 0.40,
        "display_order": 1,
        "criteria": [
            # Two auto-computed criteria. Points are filled from the worker's
            # actual orders / services vs their daily_orders_target /
            # daily_services_target. GMs can't edit these manually.
            {"name": "Total Orders",   "max_points": 100.0, "display_order": 1, "auto_source": "orders"},
            {"name": "Total Services", "max_points": 100.0, "display_order": 2, "auto_source": "services"},
        ],
    },
    {
        "name": "Attendance / Punctuality",
        "weight": 0.15,
        "display_order": 2,
        "criteria": [
            {"name": "Attendance",  "max_points": 10.0, "display_order": 1},
            {"name": "Punctuality", "max_points": 15.0, "display_order": 2},
        ],
    },
    {
        "name": "SOP Compliance",
        "weight": 0.15,
        "display_order": 3,
        "criteria": [
            {"name": "Follow Procedure",  "max_points": 9.0, "display_order": 1},
            {"name": "Use of Tools",      "max_points": 8.0, "display_order": 2},
            {"name": "Safety Violation",  "max_points": 8.0, "display_order": 3},
        ],
    },
    {
        "name": "Discipline and Conduct",
        "weight": 0.15,
        "display_order": 4,
        "criteria": [
            {"name": "Rule Violation",       "max_points": 9.0, "display_order": 1},
            {"name": "Respect",              "max_points": 8.0, "display_order": 2},
            {"name": "Customer Complaints",  "max_points": 8.0, "display_order": 3},
        ],
    },
    {
        "name": "Efficiency",
        "weight": 0.15,
        "display_order": 5,
        "criteria": [
            {"name": "Efficiency", "max_points": 15.0, "display_order": 1},
            {"name": "Quality",    "max_points": 10.0, "display_order": 2},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed scorecard categories and criteria from the Application Form spec."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing scorecards, categories, and criteria before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            DailyScoreEntry.objects.all().delete()
            DailyScorecard.objects.all().delete()
            ScorecardCriterion.objects.all().delete()
            ScorecardCategory.objects.all().delete()
            self.stdout.write(self.style.WARNING("Wiped existing scorecard data."))

        created_cats = updated_cats = 0
        created_crits = updated_crits = 0

        for cat_spec in SCORECARD_STRUCTURE:
            criteria_specs = cat_spec.pop("criteria")
            defaults = {
                "weight": cat_spec["weight"],
                "display_order": cat_spec["display_order"],
                "active": True,
            }
            category, was_created = ScorecardCategory.objects.update_or_create(
                name=cat_spec["name"],
                defaults=defaults,
            )
            if was_created:
                created_cats += 1
            else:
                updated_cats += 1

            for crit_spec in criteria_specs:
                _, crit_created = ScorecardCriterion.objects.update_or_create(
                    category=category,
                    name=crit_spec["name"],
                    defaults={
                        "max_points": crit_spec["max_points"],
                        "display_order": crit_spec["display_order"],
                        "active": True,
                        "auto_source": crit_spec.get("auto_source", ""),
                    },
                )
                if crit_created:
                    created_crits += 1
                else:
                    updated_crits += 1

        total_weight = sum(
            c.weight for c in ScorecardCategory.objects.filter(active=True)
        )

        self.stdout.write(self.style.SUCCESS(
            f"Categories: {created_cats} created, {updated_cats} updated.\n"
            f"Criteria:   {created_crits} created, {updated_crits} updated.\n"
            f"Active category weight total: {total_weight:.3f} "
            f"{'(balanced)' if abs(total_weight - 1.0) < 1e-4 else '(WARNING: not 1.000)'}"
        ))