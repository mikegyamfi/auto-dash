# management/commands/dedupe_revenue.py
from django.core.management.base import BaseCommand
from django.db.models import Count, Min
from autodash_App.models import Revenue


class Command(BaseCommand):
    help = "Remove duplicate Revenue rows, keeping the oldest per order."

    def handle(self, *args, **opts):
        dup_ids = (Revenue.objects
                   .values("service_rendered")
                   .annotate(ct=Count("id"), oldest=Min("id"))
                   .filter(ct__gt=1))
        total_removed = 0
        for row in dup_ids:
            q = Revenue.objects.filter(service_rendered=row["service_rendered"]) \
                               .exclude(id=row["oldest"])
            total_removed += q.count()
            q.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {total_removed} duplicate rows"))
