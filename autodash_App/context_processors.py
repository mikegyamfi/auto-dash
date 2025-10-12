# notifications/context_processors.py
from django.utils import timezone
from django.db.models import Q

from .models import Notification
from autodash_App.models import Worker


def worker_notifications(request):
    """
    Unread notifications for the current user's branch:
      • Superusers: all branches
      • Workers/Branch-admins: only their branch
      • Others (no worker profile): no worker notifications
    """
    if not request.user.is_authenticated:
        return {}

    user = request.user
    base = Notification.objects.filter(is_read=False)

    if user.is_superuser:
        qs = base.select_related("branch").order_by("-created_at")
    else:
        try:
            worker = Worker.objects.select_related("branch").get(user=user)
        except Worker.DoesNotExist:
            return {}
        qs = (
            base.filter(branch=worker.branch)
                .select_related("branch")
                .order_by("-created_at")
        )

    unread_count = qs.count()
    latest_unread = list(qs[:10])

    return {
        "notif_unread_count": unread_count,
        "notif_latest_unread": latest_unread,
        "notif_has_unread": unread_count > 0,
    }
