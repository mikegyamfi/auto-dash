# in your_app/decorators.py
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def staff_or_branch_admin_required(view_func):
    """
    Like @staff_member_required, but also allows workers
    whose worker_profile.is_branch_admin == True.
    """

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        u = request.user
        # superusers and staff always allowed
        if u.is_superuser or u.is_staff:
            return view_func(request, *args, **kwargs)

        # branch‐admins: must have a worker_profile with is_branch_admin
        wp = getattr(u, 'worker_profile', None)
        if wp and wp.is_branch_admin:
            return view_func(request, *args, **kwargs)

        # otherwise, no perms
        raise PermissionDenied

    return _wrapped
