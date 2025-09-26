import base64
import json
import uuid
from decimal import Decimal

import openpyxl
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.core.signing import TimestampSigner
from django.db import transaction
from django.db.models.functions import TruncDate, Concat, Coalesce
from django.forms import modelformset_factory
from django.http import (
    JsonResponse, HttpResponseForbidden
)
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from qrcode import QRCode
from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from decorators import staff_or_branch_admin_required
from . import models, forms
from .forms import (
    LogServiceForm, BranchForm, ExpenseForm, EnrollWorkerForm, CreateCustomerForm,
    CreateVehicleForm, EditCustomerVehicleForm, CustomerEditForm, LogServiceScannedForm, CustomerProfileForm
)
from .helper import send_sms
from .models import (
    CustomerSubscription, CustomUser,
    Service, LoyaltyTransaction, VehicleGroup, Subscription, WorkerCategory, CustomerSubscriptionTrail,
    CustomerSubscriptionRenewalTrail, WeeklyBudget,
    SalesTarget, WorkerEducation, WorkerEmployment, WorkerReference, WorkerGuarantor, DailySalesTarget,
    WorkerDailyAdjustment
)
from .models import (
    DailyExpenseBudget
)
from .subscription import assert_unique_active_subscription


def _get_admin_branch(request):
    """
    Returns the Branch this “admin” should be scoped to, or None if they
    still need to pick one (i.e. real staff with no ?branch_id).
    - A true superuser/is_staff can pick via ?branch_id or ?branch.
    - A branch-admin (Worker.is_branch_admin) always gets their own branch.
    """
    user = CustomUser.objects.get(id=request.user.id)

    # 1) Non-staff branch-admins see only their branch
    try:
        worker = user.worker_profile
    except (AttributeError, Worker.DoesNotExist):
        worker = None

    if worker and worker.is_branch_admin and not user.is_staff and not user.is_superuser:
        return worker.branch

    # 2) Staff/superuser can choose via GET param
    branch_id = request.GET.get('branch_id') or request.GET.get('branch')
    if branch_id:
        return get_object_or_404(Branch, id=branch_id)

    # 3) No branch yet
    return None


def _get_user_branch(request):
    """Return the branch for a branch-admin, otherwise None."""
    user = CustomUser.objects.get(id=request.user.id)
    try:
        worker = user.worker_profile
    except (AttributeError, Worker.DoesNotExist):
        return None
    if worker.is_branch_admin and not user.is_staff and not user.is_superuser:
        return worker.branch
    return None


def get_admin_date_range(date_str, month_str, year_str):
    """
    Return (start_date, end_date) based on admin's filter:
     - If date_str is given => that exact single date
     - Else if month_str + year_str => entire month
     - Else => default to today
    """
    now = timezone.now().date()

    # 1) exact date
    if date_str:
        try:
            parsed_day = datetime.strptime(date_str, '%Y-%m-%d').date()
            return parsed_day, parsed_day
        except ValueError:
            return now, now

    # 2) month + year
    elif month_str and year_str:
        try:
            y = int(year_str)
            m = int(month_str)
            start_d = date(y, m, 1)
            if m == 12:
                # next is january of next year
                end_d = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                end_d = date(y, m + 1, 1) - timedelta(days=1)
            return start_d, end_d
        except ValueError:
            return now, now

    # 3) default => today
    else:
        return now, now


@login_required(login_url='login')
def home(request):
    from django.db.models import Sum, F, Value, CharField
    from django.db.models.functions import Coalesce
    user = request.user

    # 1) Detect branch-admin flag
    is_branch_admin = False
    branch_admin_profile = None
    if hasattr(user, 'worker_profile') and user.worker_profile.is_branch_admin:
        is_branch_admin = True
        branch_admin_profile = user.worker_profile

    # ----------------------------- WORKER FLOW -----------------------------
    if not user.is_staff and not user.is_superuser and not is_branch_admin:
        try:
            worker = Worker.objects.get(user=user)
        except Worker.DoesNotExist:
            messages.error(request, "No worker profile found.")
            return redirect("logout")

        branch = worker.branch
        today = timezone.localdate()

        # ── today’s commission ────────────────────────────────────────────
        commission_today = (Commission.objects
                            .filter(worker=worker, date=today)
                            .aggregate(sum=Sum("amount"))["sum"] or 0)

        # ── today’s bonus / deduction (WorkerDailyAdjustment) ─────────────
        adj = WorkerDailyAdjustment.objects.filter(worker=worker, date=today).first()
        bonus_today = adj.bonus if adj else 0
        deduction_today = adj.deduction if adj else 0
        earnings_today = commission_today - deduction_today + bonus_today

        # ── services rendered today ───────────────────────────────────────
        service_orders_today = (ServiceRenderedOrder.objects
                                .filter(workers=worker, date__date=today)
                                .distinct())
        services_count_today = (ServiceRendered.objects
                                .filter(order__in=service_orders_today)
                                .count())

        # total sales for *this worker’s* orders
        sales_today = (service_orders_today
                       .aggregate(sum=Sum("final_amount"))["sum"] or 0)

        # ratings
        avg_rating = worker.average_rating()
        full = int(avg_rating)
        half = (avg_rating - full) >= 0.5
        empty = 5 - full - (1 if half else 0)

        # 5 most recent & any pending for this worker
        recent_services = (ServiceRenderedOrder.objects
                           .filter(workers=worker)
                           .order_by("-date")[:5])
        pending_services = (ServiceRenderedOrder.objects
                            .filter(workers=worker, status="pending")
                            .order_by("-date"))

        return render(request, "layouts/workers/worker_dashboard.html", {
            "worker": worker,
            "branch": branch,

            # ★ rating widgets
            "average_rating": avg_rating,
            "full_stars": range(full),
            "has_half": half,
            "empty_stars": range(empty),

            # counters / money
            "service_orders_today": service_orders_today.count(),
            "services_count_today": services_count_today,
            "sales_today": sales_today,
            "commission_today": commission_today,
            "deduction_today": deduction_today,
            "bonus_today": bonus_today,
            "earnings_today": earnings_today,

            # lists
            "recent_services": recent_services,
            "pending_services": pending_services,
        })

    # ----------------------------- ADMIN / BRANCH-ADMIN FLOW -----------------------------
    if is_branch_admin:
        branch = branch_admin_profile.branch
    else:
        branch_id = request.GET.get('branch_id')
        if not branch_id:
            return render(request, 'layouts/admin/select_branch.html', {
                'branches': Branch.objects.all()
            })
        branch = get_object_or_404(Branch, id=branch_id)

    # parse & validate date range
    start_str = request.GET.get('start_date', '')
    end_str = request.GET.get('end_date', '')
    today = timezone.now().date()
    if not start_str and not end_str:
        start_dt = end_dt = today
    else:
        try:
            start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_dt = today
            messages.warning(request, "Invalid start date; defaulting to today.")
        try:
            end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            end_dt = today
            messages.warning(request, "Invalid end date; defaulting to today.")
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt

    # 1) Core aggregates
    expenses_total = Expense.objects.filter(branch=branch, date__range=[start_dt, end_dt]) \
                         .aggregate(total=Sum('amount'))['total'] or 0
    revenue_total = Revenue.objects.filter(branch=branch, date__range=[start_dt, end_dt]) \
                        .aggregate(total=Sum('final_amount'))['total'] or 0
    print(revenue_total)
    commission_total = Commission.objects.filter(worker__branch=branch, date__range=[start_dt, end_dt]) \
                           .aggregate(total=Sum('amount'))['total'] or 0

    gross_sales = revenue_total - commission_total
    net_sales = gross_sales - expenses_total

    # 2) Cash-Flow breakdown
    completed = ServiceRenderedOrder.objects.filter(
        branch=branch,
        status='completed',
        date__date__range=[start_dt, end_dt]
    )
    cash_flow_cash = (
        completed
        .filter(payment_method='cash')
        .aggregate(total=Coalesce(Sum('cash_paid'), 0.0))['total']
    )
    print(cash_flow_cash)
    cash_flow_momo = (
        completed
        .filter(payment_method='momo')
        .aggregate(total=Coalesce(Sum('cash_paid'), 0.0))['total']
    )
    cash_flow_subscription = completed.aggregate(Sum('subscription_amount_used'))[
                                 'subscription_amount_used__sum'] or 0
    cash_flow_loyalty = completed.aggregate(Sum('loyalty_points_amount_deduction'))[
                            'loyalty_points_amount_deduction__sum'] or 0
    cash_flow_credit = ServiceRenderedOrder.objects.filter(
        branch=branch,
        status='onCredit',
        date__date__range=[start_dt, end_dt]
    ).aggregate(Sum('final_amount'))['final_amount__sum'] or 0

    # 3) Build list of days in the range
    num_days = (end_dt - start_dt).days + 1
    all_dates = [start_dt + timedelta(days=i) for i in range(num_days)]

    # 4) Sales Target (sum DailySalesTarget for each weekday)
    sales_target = 0
    for d in all_dates:
        dst = DailySalesTarget.objects.filter(branch=branch, weekday=d.weekday()).first()
        if dst:
            sales_target += dst.target_amount

    # 5) Expense Budget (sum WeeklyBudget for each weekday)
    expense_budget = 0
    for d in all_dates:
        wb = WeeklyBudget.objects.filter(branch=branch, weekday=d.weekday()).first()
        if wb:
            expense_budget += wb.budget_amount

    sales_status_pct = (revenue_total / sales_target * 100) if sales_target else 0
    expense_status_pct = (expenses_total / expense_budget * 100) if expense_budget else 0

    CAP = 100

    if revenue_total > sales_target:
        base = revenue_total - max(sales_target - commission_total, 0)
        incentive_amount = max(base * 0.05, 0)
        incentive_amount = min(incentive_amount, CAP)
    else:
        incentive_amount = 0

    recent_services = ServiceRenderedOrder.objects.filter(
        branch=branch,
        date__date__range=[start_dt, end_dt]
    ).order_by('-date')[:5]
    pending_services = ServiceRenderedOrder.objects.filter(
        branch=branch,
        status='pending',
        date__date__range=[start_dt, end_dt]
    ).order_by('-date')

    completed_qs = ServiceRenderedOrder.objects.filter(
        branch=branch,
        status='completed',
        date__date__range=[start_dt, end_dt]
    )

    #  TOP-5 CUSTOMERS (BY REVENUE)
    top5_customers = (
        completed_qs
        .values(cust_id=F('customer_id'))
        .annotate(
            cust_name=Concat(
                F('customer__user__first_name'), Value(' '),
                F('customer__user__last_name'),
                output_field=CharField()),
            revenue=Sum('final_amount')
        )
        .order_by('-revenue')[:5]
    )

    #  TOP-5 SERVICES (BY REVENUE)
    top5_services = (
        ServiceRendered.objects
        .filter(order__in=completed_qs)
        .values(svc=F('service__service_type'))
        .annotate(
            revenue=Sum(
                Coalesce('negotiated_price', F('service__price'))
            )
        )
        .order_by('-revenue')[:5]
    )

    #  TOP-5 WORKERS (BY REVENUE)
    top5_workers = (
        completed_qs
        .values(worker_id=F('workers'))
        .annotate(
            worker_name=Concat(
                F('workers__user__first_name'), Value(' '),
                F('workers__user__last_name'),
                output_field=CharField()),
            revenue=Sum('final_amount')
        )
        .order_by('-revenue')[:5]
    )

    #  STOCK-OUT LIST ( <= 0 )
    stock_out = (
        Product.objects
        .filter(branch=branch, stock__lte=0)
        .values('name', 'stock')
        .order_by('name')
    )
    # ────────────────────────────────────────────────────

    ps_qs = ProductSale.objects.filter(
        branch=branch,
        date_sold__date__range=[start_dt, end_dt]
    )

    products_sold_qty = ps_qs.aggregate(q=Sum('quantity'))['q'] or 0
    products_sold_amt = ps_qs.aggregate(a=Sum('total_price'))['a'] or 0

    margin_total = 0
    cat_cards = []  # what each category card needs
    cat_tables = {}  # full breakdown keyed by category id ➜ list of rows

    from django.db.models import F, Sum

    # annotate once with margin for speed
    ps_with_margin = ps_qs.annotate(
        margin_each=(F('product__price') - F('product__cost')) * F('quantity')
    )

    # 1. per-category roll-up
    for row in (
            ps_with_margin.values('product__category', 'product__category__name')
                    .annotate(
                cat_qty=Sum('quantity'),
                cat_amt=Sum('total_price'),
                cat_margin=Sum('margin_each')
            )
    ):
        cid = row['product__category']
        cat_cards.append({
            "id": cid,
            "name": row['product__category__name'] or "Uncategorised",
            "qty": row['cat_qty'] or 0,
            "amt": row['cat_amt'] or 0,
            "margin": row['cat_margin'] or 0,
        })
        margin_total += row['cat_margin'] or 0

    # 2. per-product table for each category
    for cid in [c["id"] for c in cat_cards]:
        prod_rows = []
        for p in (
                ps_with_margin
                        .filter(product__category_id=cid)
                        .values('product__id',
                                'product__name',
                                'product__stock',
                                'product__price',
                                'product__cost')
                        .annotate(
                    qty=Sum('quantity'),
                    sales=Sum('total_price'),
                    margin=Sum('margin_each')
                )
        ):
            prod_rows.append({
                "name": p['product__name'],
                "qty": p['qty'],
                "sales": p['sales'],
                "margin": p['margin'],
                "stock": p['product__stock'],
            })
        cat_tables[str(cid)] = prod_rows  # key must be str for JSON

    def count_status(status):
        return ServiceRenderedOrder.objects.filter(
            branch=branch,
            status=status,
            date__date__range=[start_dt, end_dt]
        ).count()

    # 9) Context & render
    context = {
        'is_admin': True,
        'branch': branch,

        'start_date_str': start_str,
        'end_date_str': end_str,
        'start_dt': start_dt,
        'end_dt': end_dt,

        # core metrics
        'revenue_today': revenue_total,
        'expenses_today': expenses_total,
        'total_commission': commission_total,
        'gross_sales': gross_sales,
        'net_sales': net_sales,

        'products_sold_today': products_sold_qty,
        'products_sold_amount_today': products_sold_amt,

        # cash flow
        'cash_flow_cash': cash_flow_cash,
        'cash_flow_momo': cash_flow_momo,
        'cash_flow_credit': cash_flow_credit,
        'cash_flow_subscription': cash_flow_subscription,
        'cash_flow_loyalty': cash_flow_loyalty,

        # targets & budgets
        'sales_target': sales_target,
        'expense_budget': expense_budget,
        'sales_status_pct': sales_status_pct,
        'expense_status_pct': expense_status_pct,
        'incentive_amount': incentive_amount,

        # order counts
        'total_orders': ServiceRenderedOrder.objects.filter(
            branch=branch,
            date__date__range=[start_dt, end_dt]
        ).count(),
        'completed_orders_count': count_status('completed'),
        'pending_orders_count': count_status('pending'),
        'canceled_orders_count': count_status('canceled'),
        'on_credit_orders_count': count_status('onCredit'),

        # lists
        'recent_services': recent_services,
        'pending_services': pending_services,
    }

    show_margin = request.user.is_superuser

    context.update({
        # quick totals
        "prod_qty": products_sold_qty,
        "prod_sales": products_sold_amt,
        "prod_margin": margin_total,

        # cards & tables
        "prod_cat_cards": cat_cards,
        "prod_cat_tables": json.dumps(cat_tables, default=float),
        "show_margin": show_margin,
        "top5_customers": top5_customers,
        "top5_services": top5_services,
        "top5_workers": top5_workers,
        "stock_out": stock_out,
    })

    return render(request, 'layouts/admin/dashboard.html', context)


# ---------- Utility function to send email ----------
# def send_service_email(service_order):
#     """
#     Sends an email to the customer, letting them know the details of their service.
#     Customize the email content as needed.
#     """
#     customer_email = service_order.customer.user.email
#     if not customer_email:
#         return  # no email provided, skip
#
#     subject = f"Service Update for Order {service_order.service_order_number}"
#     # Prepare context for the template or plain text
#     context = {
#         'service_order': service_order,
#         'status': service_order.status,
#         'vehicle': service_order.vehicle,
#         'final_amount': service_order.final_amount,
#         'branch': service_order.branch,
#     }
#
#     # You can render a template:
#     email_body = render_to_string('email_templates/service_update.html', context)
#
#     # Send using Django's send_mail or EmailMultiAlternatives
#     send_mail(
#         subject=subject,
#         message=email_body,  # plain text
#         from_email='autodashgh@yahoo.com',
#         recipient_list=[customer_email],
#         fail_silently=True,
#     )
#
#     # Optionally, for HTML emails:
#     # msg = EmailMultiAlternatives(
#     #     subject=subject,
#     #     body="Your service details",
#     #     from_email='yourcarwash@example.com',
#     #     to=[customer_email]
#     # )
#     # msg.attach_alternative(email_body, "text/html")
#     # msg.send()


@login_required(login_url='login')
@transaction.atomic
def log_service(request):
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, 'You are not authorized to log services.')
        return redirect('index')

    if request.method == 'POST':
        form = LogServiceForm(data=request.POST, branch=worker.branch)
        if not form.is_valid():
            messages.error(request, "Form is invalid. Please correct the errors.")
            return render(request, 'layouts/workers/log_service.html', {
                'form': form,
                'products': Product.objects.filter(branch=worker.branch),
                'vehicle_groups': VehicleGroup.objects.all(),
            })

        customer = form.cleaned_data['customer']
        vehicle = form.cleaned_data['vehicle']
        selected_services = form.cleaned_data['service']
        selected_workers = form.cleaned_data['workers']
        comments = form.cleaned_data['comments']

        if not customer:
            vehicle_customer = vehicle.customer
            if not vehicle_customer:
                pass
            else:
                customer = vehicle_customer
                to_be_saved_customer = customer

        selected_products = form.cleaned_data.get('products', [])
        product_quantities = request.POST.getlist('product_quantity')

        if not selected_services:
            messages.error(request, "Please select at least one service.")
            return render(request, 'layouts/workers/log_service.html', {
                'form': form,
                'products': Product.objects.filter(branch=worker.branch),
                'vehicle_groups': VehicleGroup.objects.all(),
            })

        total_services = Decimal('0.00')
        for svc in selected_services:
            price = Decimal(str(svc.price or 0))
            total_services += price

        total = total_services

        new_order = ServiceRenderedOrder.objects.create(
            customer=customer if customer else to_be_saved_customer,
            user=user,
            total_amount=float(total),
            final_amount=float(total),
            vehicle=vehicle,
            branch=worker.branch,
            status='pending',
            comments=comments
        )
        if selected_workers:
            new_order.workers.set(selected_workers)

        # Create line items
        for svc in selected_services:
            sr = ServiceRendered.objects.create(
                service=svc,
                order=new_order,
                negotiated_price=svc.price,   # matches FloatField
                payment_type="Cash"
            )
            if selected_workers:
                sr.workers.set(selected_workers)

        messages.success(request, 'Service logged successfully (status=pending).')
        return redirect('confirm_service_rendered', pk=new_order.pk)

    # GET
    form = LogServiceForm(branch=worker.branch)
    products = Product.objects.filter(branch=worker.branch)
    vehicle_groups = VehicleGroup.objects.all()
    return render(request, 'layouts/workers/log_service.html', {
        'form': form,
        'products': products,
        'vehicle_groups': vehicle_groups
    })


from django.urls import reverse


@login_required(login_url='login')
@transaction.atomic
def confirm_service(request, pk):
    """
    Finalise an individual ServiceRenderedOrder:
        * negotiate prices
        * allocate subscription / loyalty coverage
        * compute cash due, discounts, commissions
        * toggle status
        * (Revenue rows are now created by the post-save signal)
    """
    user = request.user
    worker = get_object_or_404(Worker, user=user)
    order = get_object_or_404(ServiceRenderedOrder, pk=pk)
    sr_list = list(order.rendered.select_related("service__category"))
    customer = order.customer

    # ────────────────────────────────────
    #  Subscription / loyalty preparation
    # ────────────────────────────────────
    subscription_active = False
    cust_sub = None
    loyalty_pts = float(customer.loyalty_points) if customer else 0.0

    if customer:
        try:
            latest = (
                CustomerSubscription.objects
                .filter(customer=customer)
                .latest("end_date")
            )
            if latest.is_active() and latest.sub_amount_remaining > 0:
                subscription_active = True
                cust_sub = latest
        except CustomerSubscription.DoesNotExist:
            pass

    # ────────────────────────────────────
    #  GET  → preview
    # ────────────────────────────────────
    if request.method == "GET":
        covered_details = []
        sim_sub_remaining = float(cust_sub.sub_amount_remaining) if cust_sub else 0
        total_cash_est = 0.0

        for sr in sr_list:
            default_p = float(sr.service.price)
            negotiated_p = float(sr.negotiated_price or default_p)
            negotiable = bool(sr.service.category and sr.service.category.negotiable)
            category_name = sr.service.category.name if sr.service.category else ""

            # subscription cover preview
            sub_cover = 0.0
            if (subscription_active and order.vehicle and cust_sub and
                    sr.service in cust_sub.subscription.services.all() and
                    order.vehicle.vehicle_group in cust_sub.subscription.vehicle_group.all()):
                sub_cover = min(negotiated_p, sim_sub_remaining)
                sim_sub_remaining -= sub_cover

            cash_due = negotiated_p - sub_cover
            total_cash_est += cash_due

            covered_details.append({
                "service_id": sr.id,
                "service_name": sr.service.service_type,
                "category": category_name,
                "default_price": default_p,
                "negotiated_price": negotiated_p,
                "negotiable": negotiable,
                "sub_cover": sub_cover,
                "cash_due": cash_due,
                "loyalty_eligible": (
                        customer and
                        0 < sr.service.loyalty_points_required <= loyalty_pts
                ),
            })

        return render(
            request,
            "layouts/workers/confirm_service_order.html",
            {
                "order": order,
                "covered_details": covered_details,
                "total_cash_est": total_cash_est,
                "subscription_active": subscription_active,
                "sub_name": cust_sub.subscription.name if cust_sub else "",
                "cust_sub_remaining": float(cust_sub.sub_amount_remaining) if cust_sub else 0.0,
                "has_sub_remaining": bool(cust_sub and cust_sub.sub_amount_remaining > 0),
                "sub_expires": cust_sub.end_date if cust_sub else None,
                "loyalty_points": loyalty_pts,
            },
        )

    # ────────────────────────────────────
    #  POST → finalise
    # ────────────────────────────────────
    # 1. negotiated prices
    total_services = 0.0
    for sr in sr_list:
        if sr.service.category and sr.service.category.negotiable:
            raw = request.POST.get(f"negotiated_{sr.id}", "")
            try:
                np = float(raw)
            except ValueError:
                messages.error(request, "Invalid negotiated price.")
                return redirect("confirm_service", pk=pk)
            if np <= 0:
                messages.error(request, "Negotiated price must be greater than zero.")
                return redirect("confirm_service", pk=pk)
            sr.negotiated_price = np
            sr.save()
            total_services += np
        else:
            total_services += float(sr.service.price)

    order.total_amount = total_services
    order.save()  # NOTE: triggers signal for Revenue if status already terminal

    # 2. status change
    new_status = request.POST.get("status", "completed")
    order.status = new_status
    order.save()  # NOTE: Revenue handled by post-save signal now

    # ────────────────────────────────────
    # INITIAL TRIGGER SMS WHEN SAVED AS PENDING (once per order)
    # ────────────────────────────────────
    if new_status == "pending" and not getattr(order, "initial_sms_sent", False):
        TRIGGER_SERVICE_NAMES = {
            "Exterior Detailing",
            "Interior Detailing",
            "Ext Polishing",
            "Mineral Deposit Removal",
        }
        TRIGGER_KEYS = {" ".join(n.split()).casefold() for n in TRIGGER_SERVICE_NAMES}

        matched_display_names = []
        for sr in sr_list:
            raw = (sr.service.service_type or "").strip()
            key = " ".join(raw.split()).casefold()
            if key in TRIGGER_KEYS:
                matched_display_names.append(raw)

        phone = getattr(getattr(order.customer, "user", None), "phone_number", None)

        if matched_display_names and phone:
            # de-dupe, keep order
            seen = set()
            unique_names = []
            for n in matched_display_names:
                if n not in seen:
                    seen.add(n)
                    unique_names.append(n)

            def human_join(names):
                if len(names) == 1:
                    return names[0]
                if len(names) == 2:
                    return f"{names[0]} and {names[1]}"
                return f"{', '.join(names[:-1])} and {names[-1]}"

            service_names_str = human_join(unique_names)
            car_number = getattr(order.vehicle, "car_plate", "") or "your vehicle"

            from decimal import Decimal
            amt = Decimal(str(order.total_amount or 0)).quantize(Decimal("0.01"))
            amount_text = f"GHS{amt}"

            sms_text = (
                f"Hello, {service_names_str} on {car_number} is confirmed. "
                f"Amount to be paid is {amount_text}. Thank you for choosing us."
            )

            # mark sent before queuing to avoid duplicates on re-submit
            order.initial_sms_sent = True
            order.save(update_fields=["initial_sms_sent"])

            def _send_initial():
                try:
                    send_sms(phone, sms_text)
                except Exception as e:
                    print(e)

            transaction.on_commit(_send_initial)

    if new_status in ("pending", "canceled"):
        messages.info(request, f"Order marked {new_status}.")
        return redirect("service_history")

    # 3. commission rollback if needed
    if new_status in ("pending", "canceled"):
        for sr in sr_list:
            sr.remove_commission()

    # 4. coverage calculations  (UPDATED: clean Cash vs Momo, no duplicates)
    remaining_sub = float(cust_sub.sub_amount_remaining) if cust_sub else 0.0
    used_sub_total = 0.0
    used_loyalty_pts = 0
    loyalty_cover = 0.0
    cash_total = 0.0

    for sr in sr_list:
        price = float(sr.get_effective_price())

        # Always rebuild label fresh for this SR
        sr.payment_type = ""

        parts = []  # collect unique parts in order

        # subscription
        sub_cov = 0.0
        if (
            subscription_active
            and order.vehicle
            and cust_sub
            and sr.service in cust_sub.subscription.services.all()
            and order.vehicle.vehicle_group in cust_sub.subscription.vehicle_group.all()
            and remaining_sub > 0.0
        ):
            sub_cov = min(price, remaining_sub)
            remaining_sub -= sub_cov
            used_sub_total += sub_cov
            parts.append("Subscription")

        leftover = price - sub_cov

        # loyalty
        loy_cov = 0.0
        if leftover > 0 and request.POST.get(f"use_loyalty_{sr.id}") and customer:
            req_pts = sr.service.loyalty_points_required
            if customer.loyalty_points >= req_pts:
                loy_cov = leftover
                used_loyalty_pts += req_pts
                loyalty_cover += loy_cov
                customer.loyalty_points -= req_pts
                parts.append("Loyalty")
                LoyaltyTransaction.objects.create(
                    customer=customer,
                    points=-req_pts,
                    transaction_type="redeem",
                    description=f"Redeemed for {sr.service.service_type}",
                    branch=order.branch,
                    order=order,
                )
        leftover -= loy_cov

        # cash / momo distinction
        if leftover > 0:
            pay_method = (request.POST.get(f"pay_method_{sr.id}", "cash") or "cash").lower()
            cash_label = "Momo" if pay_method == "momo" else "Cash"
            # optionally persist selected method if you have this field
            try:
                order.payment_method = pay_method
                order.save()
            except Exception as e:
                print(e)
                pass
            parts.append(cash_label)
            cash_total += leftover

        # De-duplicate while preserving order
        seen = set()
        unique_parts = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique_parts.append(p)

        # Final label: single if one, joined if multiple
        sr.payment_type = " + ".join(unique_parts)

        # subscription trail
        if sub_cov > 0:
            order.subscription_package_used = cust_sub
            from .models import CustomerSubscriptionTrail
            CustomerSubscriptionTrail.objects.create(
                subscription=cust_sub,
                amount_used=sub_cov,
                remaining_balance=remaining_sub,
                date_used=timezone.now(),
                customer=customer,
                order=order,
            )

        sr.save()

    # persist subscription & customer
    if cust_sub:
        cust_sub.sub_amount_remaining = remaining_sub
        cust_sub.used_amount += used_sub_total
        cust_sub.save()
    if customer:
        customer.save()

    # 5. discounts
    d_type = request.POST.get("discount_type", "amount")
    try:
        d_val = float(request.POST.get("discount_value", "0") or 0)
    except ValueError:
        d_val = 0.0
    disc_amt = (
        min(cash_total, d_val) if d_type == "amount"
        else cash_total * min(d_val, 100.0) / 100.0
    )
    const_final_cash = max(0.0, cash_total - disc_amt)
    final_cash = const_final_cash  # keep original naming

    # 6. finalise order totals
    order.subscription_amount_used = used_sub_total
    order.loyalty_points_used = used_loyalty_pts
    order.loyalty_points_amount_deduction = loyalty_cover
    order.cash_paid = final_cash
    order.discount_type = d_type
    order.discount_value = d_val
    order.final_amount = final_cash
    order.save()  # signal updates/creates Revenue here

    # 7. arrears bookkeeping
    if new_status == "onCredit":
        Arrears.objects.get_or_create(
            service_order=order,
            branch=order.branch,
            defaults={"amount_owed": final_cash},
        )
    else:
        # remove arrears if status no longer onCredit
        if hasattr(order, "arrears"):
            order.arrears.delete()

    # 8. commissions (unchanged, signal afterwards keeps Revenue up-to-date)
    for sr in sr_list:
        sr.remove_commission()
    if new_status == "onCredit":
        factor = 1
    else:
        factor = (
            (order.subscription_amount_used or 0)
            + (order.loyalty_points_amount_deduction or 0)
            + (order.cash_paid or 0)
        ) / max(order.total_amount, 1.0)
    for sr in sr_list:
        sr.allocate_commission(discount_factor=factor)

    # 9. loyalty earned
    if new_status == "completed" and customer:
        earned = sum(float(sr.service.loyalty_points_earned) for sr in sr_list)
        if earned > 0:
            customer.loyalty_points += earned
            customer.save()
            LoyaltyTransaction.objects.create(
                customer=customer,
                points=int(earned),
                transaction_type="gain",
                description=f"Loyalty earned for {order.service_order_number}",
                branch=order.branch,
                order=order,
            )

    # 10. SMS (finals for completed/onCredit only — trigger text NOT used here)
    from decimal import Decimal  # ensure this is imported at the top of the file

    phone = getattr(getattr(order.customer, "user", None), "phone_number", None)

    def _send_completed_sms():
        try:
            cash = order.cash_paid or 0.0
            plate = getattr(order.vehicle, "car_plate", "") or "your vehicle"
            send_sms(
                phone,
                (
                    f"Payment received: GHS{cash:.2f} for {plate}. "
                    f"Receipt: https://management.autodashgh.com/service/{order.id}/receipt/"
                ),
            )
        except Exception as e:
            print(e)

    def _send_credit_sms():
        try:
            owed = 0.0
            if hasattr(order, "arrears") and order.arrears and not order.arrears.is_paid:
                owed = order.arrears.amount_owed or 0.0
            else:
                owed = order.cash_paid or 0.0
            send_sms(
                phone,
                (
                    f"Service on credit: {order.service_order_number}. "
                    f"Amount owed: GHS{owed:.2f}. "
                    f"Details: https://management.autodashgh.com/service/{order.id}/receipt/"
                ),
            )
        except Exception as e:
            print(e)

    if phone:
        if new_status == "completed" and not getattr(order, "completed_sms_sent", False):
            order.completed_sms_sent = True
            order.save(update_fields=["completed_sms_sent"])
            transaction.on_commit(_send_completed_sms)

        elif new_status == "onCredit" and not getattr(order, "credit_sms_sent", False):
            order.credit_sms_sent = True
            order.save(update_fields=["credit_sms_sent"])
            transaction.on_commit(_send_credit_sms)

    messages.success(request, f"Service updated to {new_status}.")
    return redirect("service_receipt", pk=order.pk)




def service_receipt(request, pk):
    from .models import ServiceRenderedOrder, CustomerSubscriptionTrail, LoyaltyTransaction

    service_order = get_object_or_404(ServiceRenderedOrder, pk=pk)
    services_rendered = service_order.rendered.select_related('service').all()

    # Sum up final for display
    def get_price(sr):
        return sr.negotiated_price if sr.negotiated_price else sr.service.price

    total_services_price = sum(get_price(sr) for sr in services_rendered)
    # total_products_price = sum(p.total_price for p in products_purchased)
    final_amount = service_order.final_amount or 0

    # If you want to show subscription usage and loyalty transactions specifically for this order:
    subscription_trails = CustomerSubscriptionTrail.objects.filter(order=service_order)
    loyalty_transactions = LoyaltyTransaction.objects.filter(order=service_order)

    context = {
        'service_order': service_order,
        'services_rendered': services_rendered,
        'total_services_price': total_services_price,
        'final_amount': final_amount,
        'subscription_trails': subscription_trails,
        'loyalty_transactions': loyalty_transactions,
    }
    return render(request, 'layouts/workers/service_receipt.html', context)


@login_required(login_url='login')
def discard_order(request, pk):
    """
    Delete/discard an unconfirmed service order before it’s finalized.
    Make sure to revert any stock changes if you already decremented it upon creation.
    This is tricky if you already deducted stock.
    For safer approach, only deduct stock once status is confirmed.
    """
    order_to_be_discarded = get_object_or_404(ServiceRenderedOrder, pk=pk)

    # Optionally re-increment product stock for all ProductPurchased
    for prod_item in order_to_be_discarded.products_purchased.all():
        product = prod_item.product
        product.stock += prod_item.quantity
        product.save()

    order_to_be_discarded.delete()
    messages.info(request, "Order was discarded.")
    return redirect('index')


# -------------- Example: Creating a standalone product sale --------------
@login_required(login_url='login')
@transaction.atomic
def standalone_product_sale(request):
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, 'Unauthorized access.')
        return redirect('index')

    branch = worker.branch

    # 1) Gather all categories for the dropdown
    categories = ProductCategory.objects.all()

    # 2) Check if a category was selected in GET (e.g., ?category=2)
    selected_category_id = request.GET.get('category', '')

    # 3) Filter product list by category if provided, otherwise show all
    if selected_category_id:
        products = Product.objects.filter(branch=branch, category_id=selected_category_id)
    else:
        products = Product.objects.filter(branch=branch)

    if request.method == 'POST':
        raw_ids = request.POST.getlist('selected_products')
        unique_ids = list(set(raw_ids))  # <- ① deduplicate
        customer_phone = request.POST.get('customer_phone', '').strip()

        if not unique_ids:
            messages.error(request, "No products selected.")
            return redirect('sell_product')

        batch_id = uuid.uuid4()
        batch_date = timezone.now()
        sales_rows = []  # we’ll collect the created ProductSale rows

        try:
            with transaction.atomic():

                for pid in unique_ids:
                    try:
                        product = Product.objects.select_for_update().get(
                            id=pid,
                            branch=branch
                        )
                    except Product.DoesNotExist:
                        raise ValueError("Invalid product selected.")

                    # quantity_{{ product.id }} – default to 1 if the field is missing/empty
                    qty_str = request.POST.get(f'quantity_{pid}', '1')
                    try:
                        qty = max(1, int(qty_str))
                    except ValueError:
                        raise ValueError("Quantity must be a positive integer.")

                    if product.stock < qty:
                        raise ValueError(f'Not enough stock for {product.name}')

                    sale = ProductSale.objects.create(
                        user=request.user,
                        batch_id=batch_id,
                        product=product,
                        branch=branch,
                        quantity=qty,
                        total_price=product.price * qty,
                        date_sold=batch_date
                    )
                    sales_rows.append(sale)

                    # atomically drop stock
                    product.stock = F('stock') - qty  # <- ② safe decrement
                    product.save(update_fields=['stock'])

                total_price = sum(s.total_price for s in sales_rows)

                # Revenue.objects.create( ... )   # ← re-enable when your Revenue model is ready

                # optional SMS …
                # (unchanged)

                messages.success(request, "Sale recorded successfully.")
                return redirect('sell_product')

        except Exception as err:
            messages.error(request, str(err))
            return redirect('sell_product')

    # If GET, display the filtered product list and recent batches
    recent_batches = (
        ProductSale.objects.filter(branch=branch)
        .values('batch_id')
        .annotate(
            total_price=Sum('total_price'),
            date_sold=Max('date_sold'),
            item_count=Count('id')
        )
        .order_by('-date_sold')[:10]
    )

    batches_with_sales = []
    for batch in recent_batches:
        sales = ProductSale.objects.filter(batch_id=batch['batch_id']).select_related('product')
        batches_with_sales.append({
            'batch_id': batch['batch_id'],
            'date_sold': batch['date_sold'],
            'total_price': batch['total_price'],
            'sales': sales,
        })

    context = {
        'products': products,
        'recent_batches': batches_with_sales,
        'worker': worker,
        'categories': categories,  # Pass categories to the template
    }
    return render(request, 'layouts/sell_product.html', context)


@login_required(login_url='login')
def standalone_product_receipt(request, batch_id):
    """
    Displays a multi-line receipt for the standalone product sale
    identified by `batch_id`.
    """
    # Get all lines in this transaction
    sale_lines = ProductSale.objects.filter(batch_id=batch_id)
    worker = sale_lines.first().user

    # Security: if the user is a worker, ensure the lines belong to that worker's branch
    if not request.user.is_staff and not request.user.is_superuser:
        worker = get_object_or_404(Worker, user=request.user)
        # check if any line isn't from that branch => block
        if sale_lines.exists() and sale_lines.first().branch != worker.branch:
            messages.error(request, "You do not have permission to view this receipt.")
            return redirect('index')

    # Sum up total
    total_price = sum(line.total_price for line in sale_lines)

    context = {
        'sale_lines': sale_lines,
        'batch_id': batch_id,
        'total_price': total_price,
        'worker': worker
    }
    return render(request, 'layouts/sell_product_receipt.html', context)


@login_required(login_url='login')
def create_vehicle(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        if not all([customer_id, vehicle_group_id, car_make, car_plate, car_color]):
            return JsonResponse({'success': False, 'error': 'All fields are required.'})

        customer = get_object_or_404(Customer, id=customer_id)
        vehicle_group = get_object_or_404(VehicleGroup, id=vehicle_group_id)

        vehicle = CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=vehicle_group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color,
        )

        # Send SMS to the customer's phone number about new vehicle
        phone_number = customer.user.phone_number
        if phone_number:
            msg = (
                f"Dear {customer.user.first_name}, "
                f"a new vehicle ({car_make} - {car_plate}, {car_color}) has been added to your profile."
            )
            try:
                send_sms(phone_number, msg)
                print(msg)
            except Exception as e:
                print("SMS sending error:", e)

        return JsonResponse({
            'success': True,
            'vehicle': {
                'id': vehicle.id,
                'display': f"{vehicle.car_make} {vehicle.car_plate} ({vehicle.car_color})"
            }
        })

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required(login_url='login')
def add_vehicle_to_customer(request, customer_id):
    """
    Alternate method if you want a distinct endpoint for adding vehicles to a specific customer.
    """
    if request.method == 'POST':
        customer = get_object_or_404(Customer, id=customer_id)

        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        if not all([vehicle_group_id, car_make, car_plate, car_color]):
            return JsonResponse({
                'success': False,
                'message': 'All fields are required.'
            })

        vehicle_group = get_object_or_404(VehicleGroup, id=vehicle_group_id)

        vehicle = CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=vehicle_group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color,
        )

        return JsonResponse({
            'success': True,
            'vehicle': {
                'id': vehicle.id,
                'car_make': vehicle.car_make,
                'car_plate': vehicle.car_plate,
                'car_color': vehicle.car_color,
                'vehicle_group': vehicle_group.group_name,
            }
        })
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


def service_feedback_page(request, pk):
    """
    Page for customers to provide feedback and ratings for a completed service.
    Also shows the vehicle used (if any) and the customer's last service orders.
    Displays the last 3 completed orders and, if available, all onCredit orders.
    """
    service_order = get_object_or_404(ServiceRenderedOrder, id=pk)
    services_under_service_order = ServiceRendered.objects.filter(order=service_order)

    # If feedback & rating are already provided, warn the user.
    if service_order.customer_feedback and service_order.customer_rating:
        messages.success(request, 'Your feedback has already been recorded.')

    # Get recent orders for the customer if available.
    recent_completed_orders = []
    oncredit_orders = []
    if service_order.customer:
        recent_completed_orders = (
            ServiceRenderedOrder.objects
            .filter(customer=service_order.customer, status='completed')
            .exclude(pk=service_order.pk)
            .order_by('-date')[:3]
        )
        oncredit_orders = (
            ServiceRenderedOrder.objects
            .filter(customer=service_order.customer, status='onCredit')
            .order_by('-date')
        )

    if request.method == 'POST':
        rating = request.POST.get('rating')
        feedback = request.POST.get('feedback')

        service_order.customer_rating = rating
        service_order.customer_feedback = feedback
        service_order.save()

        # Update each worker's rating (assumes add_rating is implemented)
        for w in service_order.workers.all():
            w.add_rating(int(rating))
            w.save()

        messages.success(request, 'Your feedback has been recorded.')
        return redirect('thank_you_for_feedback', pk=service_order.id)

    context = {
        'service_order': service_order,
        'services': services_under_service_order,
        'recent_completed_orders': recent_completed_orders,
        'oncredit_orders': oncredit_orders,
    }
    return render(request, "layouts/service_feedback_page.html", context)


def thank_you_feedback(request, pk):
    """
    Simple 'thank you' page after customer provides feedback.
    """
    service_order = get_object_or_404(ServiceRenderedOrder, id=pk)
    stars_given = service_order.customer_rating
    return render(
        request,
        'layouts/thank_you_for_feedback.html',
        {'service_order': service_order, 'stars_given': stars_given}
    )


@login_required(login_url='login')
def service_order_details(request, pk):
    """
    View details of a specific service order (services rendered, products, etc.).
    """
    service_order = get_object_or_404(ServiceRenderedOrder, pk=pk)
    services_rendered = ServiceRendered.objects.filter(order=service_order)

    context = {
        'service_order': service_order,
        'services_rendered': services_rendered,
    }
    return render(request, 'layouts/workers/service_order_details.html', context)


@login_required(login_url='login')
def check_customer_status(request, customer_id):
    """
    AJAX endpoint to check if customer has an active subscription
    and how many loyalty points they have.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    active_subscriptions = CustomerSubscription.objects.filter(
        customer=customer,
        end_date__gte=timezone.now()
    )
    active_subscription = active_subscriptions.exists()

    return JsonResponse({
        'active_subscription': active_subscription,
        'loyalty_points': customer.loyalty_points
    })


@login_required(login_url='login')
def create_customer(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    worker = models.Worker.objects.get(user=user)
    print(worker.branchs)
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        phone_number = request.POST.get('phone_number')
        email = request.POST.get('email')
        if first_name and last_name and phone_number:
            if CustomUser.objects.filter(phone_number=phone_number).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Customer with this phone number already exists.'
                })
            new_custom_user = CustomUser.objects.create(
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                email=email,
                username=phone_number,  # e.g. use phone as username
                role='customer',
            )
            new_customer = Customer.objects.create(user=new_custom_user, branch=worker.branch)

            # Send an SMS: "Welcome to our service!"
            try:
                send_sms(
                    phone_number,
                    f"Hello {first_name}, thanks for registering with us!\nAutoDash GH welcomes you!"
                )
                print("sms")
            except Exception as e:
                print("SMS sending error:", e)

            return JsonResponse({
                'success': True,
                'customer': {
                    'id': new_custom_user.id,
                    'name': f"{new_custom_user.first_name} {new_custom_user.last_name}"
                }
            })
        return JsonResponse({'success': False, 'error': 'Missing required fields.'})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


def send_password_reset(user):
    """
    Utility function to send a password reset email to the given user.
    """
    print("Preparing to send password reset...")
    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        c = {
            "name": user.first_name,
            "email": user.email,
            "uid": uid,
            "token": token,
            'domain': 'localhost:8000',
            'site_name': 'AutoDash',
            'protocol': 'http',
        }
        email_template_name = "password/password_reset_message.txt"
        email_content = render_to_string(email_template_name, c)

        send_mail(
            subject="Password Reset Requested",
            message=email_content,
            from_email=None,  # or settings.EMAIL_HOST_USER
            recipient_list=[user.email],
            fail_silently=False,
        )
        print("Password reset email content:", email_content)


# ───────────────────────────────────────────────────────────────────────
# 2. service_history  (bulk-update flow)
# ───────────────────────────────────────────────────────────────────────
@login_required(login_url='login')
def service_history(request):
    """
    List & bulk-update ServiceRenderedOrder rows.
    Revenue rows are synchronised by the post-save signal,
    so this view no longer writes to the Revenue table.
    Workers who are not branch admins only see orders they participated in.
    """
    user = request.user

    # authorisation
    if user.role not in ["worker", "Admin"] and not user.is_staff:
        messages.error(request, "You are not authorized to view this page.")
        return redirect("index")

    # base queryset
    services_rendered = ServiceRenderedOrder.objects.all().order_by("-date")

    # branch scoping and per-worker scoping
    if not user.is_staff and not user.is_superuser:
        try:
            worker = Worker.objects.get(user=user)
        except Worker.DoesNotExist:
            messages.error(request, "No worker profile found.")
            return redirect("index")

        # limit to branch
        services_rendered = services_rendered.filter(branch=worker.branch)

        # if not a branch admin, limit to orders this worker rendered
        if not worker.is_branch_admin:
            services_rendered = (
                services_rendered
                .filter(rendered__workers=worker)
                .distinct()
            )

    # filters
    statuses = ServiceRenderedOrder.STATUS_CHOICES
    payment_methods = [
        "all", "cash", "momo", "loyalty",
        "subscription", "subscription-cash", "subscription-momo"
    ]

    status_filter = request.GET.get("status", "all")
    payment_filter = request.GET.get("payment_method", "all")

    if status_filter != "all":
        services_rendered = services_rendered.filter(status=status_filter)
    if payment_filter != "all":
        services_rendered = services_rendered.filter(payment_method=payment_filter)

    # date range filter
    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")

    today_date = timezone.now().date()
    if not start_date_str and not end_date_str:
        services_rendered = services_rendered.filter(date__date=today_date)
        start_date_str = end_date_str = today_date.strftime("%Y-%m-%d")
    else:
        try:
            start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else today_date
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else today_date
            if end_dt < start_dt:
                start_dt, end_dt = end_dt, start_dt
            services_rendered = services_rendered.filter(date__date__range=[start_dt, end_dt])
        except ValueError:
            messages.warning(request, "Invalid date format. Showing today's data.")
            services_rendered = services_rendered.filter(date__date=today_date)
            start_date_str = end_date_str = today_date.strftime("%Y-%m-%d")

    # extra branch filter for staff / superusers
    branches = None
    selected_branch_id = None
    if user.is_staff or user.is_superuser:
        branches = Branch.objects.all()
        selected_branch_id = request.GET.get("branch", "")
        if selected_branch_id:
            services_rendered = services_rendered.filter(branch_id=selected_branch_id)

    # ────────────────────────────────────
    #  bulk status update
    # ────────────────────────────────────
    if request.method == "POST":
        selected_order_ids = request.POST.getlist("selected_orders")
        new_status = request.POST.get("new_status")
        valid_statuses = [choice[0] for choice in ServiceRenderedOrder.STATUS_CHOICES]

        if not selected_order_ids or new_status not in valid_statuses:
            messages.error(request, "Please select orders and a valid status to update.")
            return redirect("service_history")

        for order_id in selected_order_ids:
            order = get_object_or_404(ServiceRenderedOrder, id=order_id)
            old_status = order.status

            # moving into completed or onCredit → recompute commissions
            if old_status not in ("completed", "onCredit") and new_status in ("completed", "onCredit"):
                # remove existing commissions
                for sr in order.rendered.all():
                    sr.remove_commission()

                # decide multiplier: full-price for onCredit, otherwise based on actual payment coverage
                if new_status == "onCredit":
                    factor = 1
                else:
                    paid = (
                            (order.subscription_amount_used or 0)
                            + (order.loyalty_points_amount_deduction or 0)
                            + (order.cash_paid or 0)
                    )
                    factor = paid / max(order.total_amount, 1.0)

                # re-allocate
                for sr in order.rendered.all():
                    sr.allocate_commission(discount_factor=factor)

            # moving out of a terminal state into pending/canceled → remove commissions
            elif old_status in ("completed", "onCredit") and new_status in ("pending", "canceled"):
                for sr in order.rendered.all():
                    sr.remove_commission()

            # apply status change
            order.status = new_status
            order.save()

            # arrears bookkeeping
            if new_status == "onCredit":
                Arrears.objects.get_or_create(
                    service_order=order,
                    branch=order.branch,
                    defaults={"amount_owed": order.final_amount or 0},
                )
            else:
                if hasattr(order, "arrears"):
                    order.arrears.delete()

        messages.success(request, "Selected orders have been updated.")
        return redirect("service_history")

    # aggregates for footer
    aggregates = services_rendered.aggregate(
        total_amount=Sum("total_amount"),
        total_final=Sum("final_amount"),
    )
    total_amount = aggregates["total_amount"] or 0
    total_final = aggregates["total_final"] or 0

    return render(
        request,
        "layouts/workers/service_history.html",
        {
            "services_rendered": services_rendered,
            "statuses": statuses,
            "status_filter": status_filter,
            "payment_methods": payment_methods,
            "payment_filter": payment_filter,
            "start_date_str": start_date_str,
            "end_date_str": end_date_str,
            "branches": branches,
            "selected_branch_id": selected_branch_id,
            "total_amount": total_amount,
            "total_final": total_final,
        },
    )


def _get_filtered_services(request):
    user = request.user
    qs = ServiceRenderedOrder.objects.all().order_by('-date')

    # worker-branch filter
    if not user.is_staff and not user.is_superuser:
        worker = Worker.objects.filter(user=user).first()
        if not worker:
            return ServiceRenderedOrder.objects.none()
        qs = qs.filter(branch=worker.branch)

    # status & payment filters
    status = request.GET.get('status', 'all')
    pay = request.GET.get('payment_method', 'all')
    if status != 'all':
        qs = qs.filter(status=status)
    if pay != 'all':
        qs = qs.filter(payment_method=pay)

    # date range
    from datetime import datetime as dt
    today = timezone.now().date()
    start = request.GET.get('start_date', '')
    end = request.GET.get('end_date', '')
    if not (start or end):
        qs = qs.filter(date__date=today)
    else:
        try:
            sd = dt.strptime(start, '%Y-%m-%d').date() if start else today
            ed = dt.strptime(end, '%Y-%m-%d').date() if end else today
            if ed < sd: sd, ed = ed, sd
            qs = qs.filter(date__date__range=[sd, ed])
        except ValueError:
            qs = qs.filter(date__date=today)

    # branch dropdown (staff)
    branch_id = request.GET.get('branch', '')
    if user.is_staff and branch_id:
        qs = qs.filter(branch_id=branch_id)

    return qs


@login_required(login_url='login')
def export_service_history_excel(request):
    services = _get_filtered_services(request)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Service History"

    # header
    ws.append([
        "Service #", "Date", "Customer", "Workers",
        "Branch", "Status", "Payment Mode", "Total", "Final"
    ])

    # rows
    for s in services:
        workers = ", ".join(
            f"{w.user.first_name} {w.user.last_name}"
            for w in s.workers.all()
        )
        ws.append([
            s.service_order_number,
            s.date.strftime('%Y-%m-%d %H:%M'),
            s.customer.user.get_full_name(),
            workers,
            s.branch.name,
            s.get_status_display(),
            s.payment_method or "-",
            float(s.total_amount),
            float(s.final_amount)
        ])

    # totals
    agg = services.aggregate(
        total_amount=Sum('total_amount'),
        total_final=Sum('final_amount'),
    )
    ws.append([])  # blank row
    ws.append([
        "Totals", "", "", "", "", "",
        "",
        agg['total_amount'] or 0,
        agg['total_final'] or 0,
    ])

    # response
    resp = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    fname = timezone.now().strftime("service_history_%Y%m%d_%H%M.xlsx")
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    wb.save(resp)
    return resp


@login_required(login_url='login')
def export_service_history_pdf(request):
    services = _get_filtered_services(request)
    agg = services.aggregate(
        total_amount=Sum('total_amount'),
        total_final=Sum('final_amount'),
    )

    html = render_to_string('layouts/admin/service_history_pdf.html', {
        'services_rendered': services,
        'total_amount': agg['total_amount'] or 0,
        'total_final': agg['total_final'] or 0,
        'now': timezone.now(),
    })

    resp = HttpResponse(content_type='application/pdf')
    fname = timezone.now().strftime("service_history_%Y%m%d_%H%M.pdf")
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'

    pisa_status = pisa.CreatePDF(html, dest=resp)
    if pisa_status.err:
        return HttpResponse("PDF generation error; please try again.")
    return resp


# ----------------------------------------------------------------
#                       CUSTOMER VIEWS
# ----------------------------------------------------------------

@login_required(login_url='login')
def customer_dashboard(request):
    """
    Dashboard for a customer user:
    - Shows recent service orders (latest 10) and full list in a modal.
    - Active subscription details (if any).
    - Recent subscription trails (latest 10) with a "View All" modal.
    - Recent loyalty transactions (latest 10) with a "View All" modal.
    - Recent subscription renewal trails (latest 10) with a "View All" modal.
    - Registered vehicles (latest 10) with a "View All" modal.
    - Any arrears.
    - Also provides a scanned URL for quick logging of services.
    """
    customer = get_object_or_404(Customer, user=request.user)

    services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')[:5]
    all_services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')

    active_subscription = CustomerSubscription.objects.filter(
        customer=customer,
        end_date__gte=timezone.now().date()
    ).first()

    subscription_trails = CustomerSubscriptionTrail.objects.filter(customer=customer).order_by('-date_used')[:5]
    all_subscription_trails = CustomerSubscriptionTrail.objects.filter(customer=customer).order_by('-date_used')

    loyalty_transactions = LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')[:5]
    all_loyalty_transactions = LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')

    renewal_trails = CustomerSubscriptionRenewalTrail.objects.filter(customer=customer).order_by('-date_renewed')[:5]
    all_renewal_trails = CustomerSubscriptionRenewalTrail.objects.filter(customer=customer).order_by('-date_renewed')

    vehicles = CustomerVehicle.objects.filter(customer=customer)[:10]
    all_vehicles = CustomerVehicle.objects.filter(customer=customer)

    arrears = Arrears.objects.filter(service_order__customer=customer, is_paid=False).order_by('-date_created')

    scanned_url = request.build_absolute_uri(reverse('log_service_scanned', args=[customer.id]))

    context = {
        'customer': customer,
        'services_rendered': services_rendered,
        'all_services_rendered': all_services_rendered,
        'active_subscription': active_subscription,
        'subscription_trails': subscription_trails,
        'all_subscription_trails': all_subscription_trails,
        'loyalty_transactions': loyalty_transactions,
        'all_loyalty_transactions': all_loyalty_transactions,
        'renewal_trails': renewal_trails,
        'all_renewal_trails': all_renewal_trails,
        'vehicles': vehicles,
        'all_vehicles': all_vehicles,
        'arrears': arrears,
        'scanned_url': scanned_url,
        'current_year': timezone.now().year,
        'loyalty_points': customer.loyalty_points,
    }
    return render(request, 'layouts/customers/customer_index.html', context)


@login_required(login_url='login')
def customer_profile(request):
    user = request.user
    if request.method == 'POST':
        form = CustomerProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('customer_profile')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CustomerProfileForm(instance=user)
    return render(request, 'layouts/customers/customer_profile.html', {'form': form})


@login_required(login_url='login')
def customer_service_history(request):
    """
    Shows a customer's own service history with filters.
    """
    user = get_object_or_404(CustomUser, id=request.user.id)
    customer = get_object_or_404(Customer, user=user)

    qs = (
        ServiceRenderedOrder.objects
        .filter(customer=customer)
        .select_related('branch')
        .prefetch_related('workers__user')
        .order_by('-date')
    )

    # ----- Filters -----
    status = request.GET.get('status', '').strip()                  # completed/pending/canceled/onCredit
    pm = request.GET.get('payment_method', '').strip()              # cash/momo
    branch_id = request.GET.get('branch', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    min_amt = request.GET.get('min_amount', '').strip()
    max_amt = request.GET.get('max_amount', '').strip()
    q = request.GET.get('q', '').strip()                            # free text search (order number)

    if status:
        qs = qs.filter(status=status)

    if pm in ('cash', 'momo'):
        qs = qs.filter(payment_method=pm)

    if branch_id.isdigit():
        qs = qs.filter(branch_id=int(branch_id))

    # dates
    if date_from:
        try:
            qs = qs.filter(date__date__gte=date_from)
        except ValueError:
            pass
    if date_to:
        try:
            qs = qs.filter(date__date__lte=date_to)
        except ValueError:
            pass

    # amounts (final_amount)
    if min_amt:
        try:
            qs = qs.filter(final_amount__gte=float(min_amt))
        except ValueError:
            pass
    if max_amt:
        try:
            qs = qs.filter(final_amount__lte=float(max_amt))
        except ValueError:
            pass

    # search by service_order_number
    if q:
        qs = qs.filter(Q(service_order_number__icontains=q))

    # For branch filter options (only those the customer actually has history with)
    branches = (
        ServiceRenderedOrder.objects
        .filter(customer=customer)
        .values('branch_id', 'branch__name')
        .distinct()
        .order_by('branch__name')
    )

    # Pagination (20 per page)
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Keep existing query params for pagination links
    querydict = request.GET.copy()
    if 'page' in querydict:
        querydict.pop('page')
    preserved_query = querydict.urlencode()

    context = {
        'services_rendered': page_obj,
        'page_obj': page_obj,
        'preserved_query': preserved_query,

        # filter option lists
        'status_choices': dict(ServiceRenderedOrder.STATUS_CHOICES),
        'branches': branches,
        'selected': {
            'status': status,
            'payment_method': pm,
            'branch': branch_id,
            'date_from': date_from,
            'date_to': date_to,
            'min_amount': min_amt,
            'max_amount': max_amt,
            'q': q,
        }
    }
    return render(request, 'layouts/customers/service_history.html', context)


@login_required(login_url='login')
def branch_customers(request):
    """
    List customers who have had services at the worker's branch.
    """
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, 'You are not authorized to view this page.')
        return redirect('index')

    branch = worker.branch
    customers = Customer.objects.filter(branch=branch)

    context = {
        'customers': customers,
    }
    return render(request, 'layouts/workers/branch_customers.html', context)


@login_required(login_url='login')
def customer_detail(request, customer_id):
    """
    Detailed view of a customer in the context of the worker's branch.
    Shows service orders, vehicles, and loyalty transactions.
    """
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, 'You are not authorized to view this page.')
        return redirect('index')

    customer = get_object_or_404(Customer, id=customer_id)
    branch = worker.branch

    # Filter service orders for the branch
    service_orders = ServiceRenderedOrder.objects.filter(
        customer=customer,
        branch=branch
    ).order_by('-date')

    vehicles = CustomerVehicle.objects.filter(customer=customer)
    loyalty_transactions = LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')
    vehicle_groups = VehicleGroup.objects.all()
    subscriptions = Subscription.objects.all()
    customer_subscriptions = CustomerSubscription.objects.filter(customer=customer)

    context = {
        'customer': customer,
        'service_orders': service_orders,
        'vehicles': vehicles,
        'loyalty_transactions': loyalty_transactions,
        'vehicle_groups': vehicle_groups,
        'subscriptions': subscriptions,
        'customer_subscriptions': customer_subscriptions
    }
    return render(request, 'layouts/workers/customer_detail.html', context)


@login_required(login_url='login')
def worker_profile(request):
    """
    Worker profile view. Allows updating GH card details or phone number,
    with phone number changes requiring approval.
    Shows worker's average rating and total services.
    """
    user = request.user
    worker = get_object_or_404(Worker, user=user)

    if request.method == 'POST':
        form = forms.WorkerProfileForm(request.POST, request.FILES, instance=worker)
        if form.is_valid():
            worker = form.save(commit=False)

            new_phone_number = form.cleaned_data.get('pending_phone_number')
            if new_phone_number != worker.user.phone_number:
                worker.pending_phone_number = new_phone_number
                worker.is_phone_number_approved = False
                messages.info(request, 'Your phone number change is pending approval.')
            else:
                worker.pending_phone_number = None
                worker.is_phone_number_approved = True

            worker.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('worker_profile')
    else:
        form = forms.WorkerProfileForm(instance=worker)

    # Calculate average rating
    completed_orders = ServiceRenderedOrder.objects.filter(
        workers__in=[worker],
        status='completed'
    )
    total_ratings = completed_orders.aggregate(Sum('customer_rating'))['customer_rating__sum'] or 0
    rating_count = completed_orders.filter(customer_rating__isnull=False).count()
    average_rating = round(total_ratings / rating_count, 2) if rating_count > 0 else 0

    # Prepare stars
    full_star_count = int(average_rating)
    has_half_star = (average_rating - full_star_count) >= 0.5
    empty_star_count = 5 - full_star_count - (1 if has_half_star else 0)

    context = {
        'worker': worker,
        'form': form,
        'average_rating': average_rating,
        'full_stars': range(full_star_count),
        'has_half_star': has_half_star,
        'empty_stars': range(empty_star_count),
        'services_count': rating_count,
    }
    return render(request, 'layouts/workers/worker_profile.html', context)


# ----------------------------------------------------------------
#                          ADMIN VIEWS
# ----------------------------------------------------------------

@staff_member_required
def approve_workers(request):
    """
    List GH-card and phone-change approvals for workers.
    """
    pending_gh_card_workers = Worker.objects.filter(
        is_gh_card_approved=False,
    ).exclude(gh_card_number__isnull=True).exclude(gh_card_number__exact='')

    pending_phone_workers = Worker.objects.filter(
        is_phone_number_approved=False
    ).exclude(pending_phone_number__isnull=True).exclude(pending_phone_number__exact='')

    context = {
        'pending_gh_card_workers': pending_gh_card_workers,
        'pending_phone_workers': pending_phone_workers,
    }
    return render(request, 'layouts/admin/approve_workers.html', context)


@staff_member_required
def approve_worker(request, worker_id, approval_type):
    """
    Approve GH card details or phone number changes for a worker.
    """
    worker = get_object_or_404(Worker, id=worker_id)
    if request.method == 'POST':
        if approval_type == 'gh_card':
            worker.is_gh_card_approved = True
            worker.save()
            messages.success(
                request,
                f"{worker.user.get_full_name()}'s GH Card details have been approved."
            )
        elif approval_type == 'phone':
            worker.is_phone_number_approved = True
            worker.user.phone_number = worker.pending_phone_number
            worker.user.save()
            worker.pending_phone_number = ''
            worker.save()
            messages.success(
                request,
                f"{worker.user.get_full_name()}'s phone number has been approved."
            )
        return redirect('approve_workers')

    messages.error(request, 'Invalid request.')
    return redirect('approve_workers')


@staff_member_required
def admin_dashboard(request):
    """
    An overall admin dashboard with analytics on branches, revenue, and services.
    """
    branches = Branch.objects.all()
    branch_data = []
    for branch in branches:
        branch_customers = Customer.objects.filter(
            servicerenderedorder__branch=branch
        ).distinct().count()
        branch_vehicles = CustomerVehicle.objects.filter(
            customer__servicerenderedorder__branch=branch
        ).distinct().count()
        branch_info = {
            'branch': branch,
            'total_customers': branch_customers,
            'total_vehicles': branch_vehicles,
        }
        branch_data.append(branch_info)

    vehicle_groups_count = VehicleGroup.objects.count()

    now = timezone.now()
    today = now.date()
    start_of_month = today.replace(day=1)
    end_of_month = today

    highest_revenue = 0
    highest_revenue_branch = None
    highest_services = 0
    highest_services_branch = None

    yearly_branch_names = []
    yearly_branch_revenues = []
    yearly_branch_services = []

    for branch in branches:
        # Monthly data
        month_orders = ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_of_month,
            date__date__lte=end_of_month
        )
        month_revenue = month_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        month_services = month_orders.count()

        if month_revenue > highest_revenue:
            highest_revenue = month_revenue
            highest_revenue_branch = branch
        if month_services > highest_services:
            highest_services = month_services
            highest_services_branch = branch

        # Yearly data
        start_of_year = today.replace(month=1, day=1)
        year_orders = ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_of_year,
            date__date__lte=end_of_month
        )
        year_revenue = year_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        year_services = year_orders.count()

        yearly_branch_names.append(branch.name)
        yearly_branch_revenues.append(year_revenue)
        yearly_branch_services.append(year_services)

    # Convert to JSON for charts
    yearly_branch_names_json = json.dumps(yearly_branch_names)
    yearly_branch_revenues_json = json.dumps(yearly_branch_revenues)
    yearly_branch_services_json = json.dumps(yearly_branch_services)
    services = Service.objects.all()

    context = {
        'branch_data': branch_data,
        'vehicle_groups_count': vehicle_groups_count,
        'highest_revenue': highest_revenue,
        'highest_revenue_branch': highest_revenue_branch,
        'highest_services': highest_services,
        'highest_services_branch': highest_services_branch,
        'yearly_branch_names_json': yearly_branch_names_json,
        'yearly_branch_revenues_json': yearly_branch_revenues_json,
        'yearly_branch_services_json': yearly_branch_services_json,
        'services': services,
    }
    return render(request, 'layouts/admin/admin_dashboard.html', context)


@staff_member_required
def get_branch_comparison_data(request):
    """
    AJAX endpoint to compare branch revenue or services over a selected time period.
    time_period: 'week' or a month number (e.g., '3' for March)
    data_type: 'revenue' or 'services'
    """
    time_period = request.GET.get('time_period', 'week')
    data_type = request.GET.get('data_type', 'revenue')
    today = timezone.now().date()

    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    else:
        try:
            month = int(time_period)
            year = today.year
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today

    branches = Branch.objects.all()
    branch_names = []
    branch_values = []

    for branch in branches:
        branch_orders = ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_date,
            date__date__lte=end_date
        )
        if data_type == 'revenue':
            total_value = branch_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        else:
            total_value = branch_orders.count()

        branch_names.append(branch.name)
        branch_values.append(total_value)

    return JsonResponse({
        'branch_names': branch_names,
        'branch_values': branch_values
    })


@staff_member_required
def get_service_performance_data(request):
    """
    AJAX endpoint to get the number of times a given service was rendered
    per branch for a selected period: 'week' or 'month'.
    """
    service_id = request.GET.get('service_id')
    time_period = request.GET.get('time_period', 'week')
    try:
        service = Service.objects.get(id=service_id)
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Service does not exist'}, status=400)

    today = timezone.now().date()
    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif time_period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today

    branches = Branch.objects.all()
    branch_names = []
    branch_values = []

    for branch in branches:
        service_rendered_orders_count = ServiceRendered.objects.filter(
            service_id=service_id,
            order__branch_id=branch.id,
            order__status='completed',
            order__date__date__gte=start_date,
            order__date__date__lte=end_date
        ).values('order').distinct().count()

        branch_names.append(branch.name)
        branch_values.append(service_rendered_orders_count)

    data = {
        'branch_names': branch_names,
        'branch_values': branch_values,
    }
    return JsonResponse(data)


@staff_member_required
def get_vehicles_data(request):
    """
    AJAX endpoint to get the count of newly added vehicles over a given period (week or month).
    """
    time_period = request.GET.get('time_period', 'week')
    today = timezone.now().date()

    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    else:
        try:
            month = int(time_period)
            year = today.year
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today

    vehicles = CustomerVehicle.objects.filter(
        date_added__gte=start_date,
        date_added__lte=end_date
    ).order_by('date_added')

    date_counts = {}
    current_date = start_date
    while current_date <= end_date:
        date_counts[current_date.strftime('%Y-%m-%d')] = 0
        current_date += timedelta(days=1)

    for v in vehicles:
        date_str = v.date_added.strftime('%Y-%m-%d')
        if date_str in date_counts:
            date_counts[date_str] += 1
        else:
            date_counts[date_str] = 1

    dates = sorted(date_counts.keys())
    values = [date_counts[d] for d in dates]

    data = {
        'dates': dates,
        'values': values,
    }
    return JsonResponse(data)


@staff_or_branch_admin_required
def manage_workers(request):
    """
    Allows staff to filter by branch/category.
    Branch-admins see only their branch, no dropdown.
    """
    # 1) check if this is a branch-admin
    branch_admin_branch = _get_user_branch(request)

    # 2) staff vs branch-admin: determine which branch to filter
    if branch_admin_branch:
        # branch-admin: ignore any GET, force their branch
        selected_branch = branch_admin_branch
    else:
        # staff: read from GET or default to None => all branches
        branch_id = request.GET.get('branch')
        selected_branch = Branch.objects.filter(id=branch_id).first() if branch_id else None
    category_id = request.GET.get('category', '')

    # 4) build queryset
    qs = Worker.objects.select_related('user', 'branch', 'worker_category').all()
    if selected_branch:
        qs = qs.filter(branch=selected_branch)
    if category_id:
        qs = qs.filter(worker_category_id=category_id)

    branches = Branch.objects.all()
    categories = WorkerCategory.objects.all()

    return render(request, 'layouts/admin/manage_workers.html', {
        'workers': qs,
        'branches': branches,
        'categories': categories,
        'selected_branch': selected_branch.id if selected_branch else '',
        'selected_category': category_id or '',
        # hide dropdown if branch-admin
        'hide_branch_selector': bool(branch_admin_branch),
    })


# views.py
@staff_member_required
def approve_worker(request, worker_id):
    worker = get_object_or_404(Worker, id=worker_id)
    user = worker.user
    user.approved = True
    user.save()
    messages.success(request, f"Worker account approved for {worker.user.get_full_name()}.")
    return redirect('manage_workers')


@staff_or_branch_admin_required
def worker_detail(request, worker_id):
    """
    Admin/branch-admin view to see & edit a specific worker,
    plus approve/unapprove/delete actions.
    """
    worker = get_object_or_404(Worker, id=worker_id)

    # Branch-admin may only view their own branch
    if (not request.user.is_superuser
            and hasattr(request.user, 'worker_profile')
            and request.user.worker_profile.is_branch_admin
            and worker.branch != request.user.worker_profile.branch):
        return HttpResponseForbidden("You may only manage workers in your branch.")

    # Only superusers or staff can actually save changes or take actions
    can_edit = request.user.is_superuser or request.user.is_staff

    if request.method == 'POST' and can_edit:
        # 1) SAVE any form edits
        if 'save' in request.POST:
            # -- User fields --
            first = request.POST.get('first_name', '').strip()
            last = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone_number', '').strip()

            # phone uniqueness check
            if phone != worker.user.phone_number and CustomUser.objects.filter(phone_number=phone).exists():
                messages.error(request, "That phone number is already in use.")
            else:
                u = worker.user
                u.first_name = first
                u.last_name = last
                u.email = email
                u.phone_number = phone
                u.save()

                # -- Worker fields --
                cat_id = request.POST.get('worker_category')
                worker.worker_category = WorkerCategory.objects.get(id=cat_id) if cat_id else None

                if request.user.is_superuser:
                    br_id = request.POST.get('branch')
                    if br_id:
                        worker.branch = Branch.objects.get(id=br_id)

                worker.position = request.POST.get('position', '').strip()
                worker.salary = request.POST.get('salary') or 0
                worker.gh_card_number = request.POST.get('gh_card_number', '').strip()
                worker.is_branch_admin = bool(request.POST.get('is_branch_admin'))
                if 'gh_card_photo' in request.FILES:
                    worker.gh_card_photo = request.FILES['gh_card_photo']
                worker.save()

                messages.success(request, "Worker details updated.")
                return redirect('worker_detail', worker_id=worker.id)

        # 2) ACTION buttons
        else:
            action = request.POST.get('action')
            if action == 'approve_gh':
                worker.is_gh_card_approved = True
                worker.save()
                messages.success(request, "GH Card approved.")
            elif action == 'unapprove_gh':
                worker.is_gh_card_approved = False
                worker.save()
                messages.success(request, "GH Card un‐approved.")
            elif action == 'approve_phone':
                worker.is_phone_number_approved = True
                worker.save()
                messages.success(request, "Phone number approved.")
            elif action == 'unapprove_phone':
                worker.is_phone_number_approved = False
                worker.save()
                messages.success(request, "Phone number un‐approved.")
            elif action == 'approve_user':
                worker.user.approved = True
                worker.user.save()
                messages.success(request, "Worker account approved.")
            elif action == 'delete':
                worker.user.delete()
                messages.success(request, "Worker deleted.")
                return redirect('manage_workers')

        return redirect('worker_detail', worker_id=worker.id)

    # GET => render form/view
    context = {
        'worker': worker,
        'branches': Branch.objects.all(),
        'categories': WorkerCategory.objects.all(),
        'can_edit': can_edit,
    }
    return render(request, 'layouts/admin/worker_detail.html', context)


@staff_or_branch_admin_required
def manage_customers(request):
    """
    Admin & branch-admin view to:
      - Filter customers by branch (staff/superuser only),
      - Branch-admins see only their own branch,
      - Reassign a customer's branch,
      - Send an SMS to the customer.
    """
    user = request.user

    # Is this a branch-admin (worker.is_branch_admin)?
    branch_admin = False
    if not (user.is_staff or user.is_superuser):
        try:
            worker = Worker.objects.get(user=user)
            branch_admin = worker.is_branch_admin
        except Worker.DoesNotExist:
            return HttpResponseForbidden("You are not authorized to view this page.")

    # 1) Determine base queryset & branch selector visibility
    if user.is_staff or user.is_superuser:
        # full admin: can pick any branch
        branches = Branch.objects.all()
        selected_branch_id = request.GET.get('branch', '')
        if selected_branch_id:
            customers_qs = Customer.objects.filter(branch_id=selected_branch_id)
        else:
            customers_qs = Customer.objects.all()
        hide_branch_selector = False

    elif branch_admin:
        # branch-admin: only their branch, no selector
        branches = None
        selected_branch_id = worker.branch.id
        customers_qs = Customer.objects.filter(branch=worker.branch)
        hide_branch_selector = True

    else:
        # neither staff/superuser nor branch-admin: forbidden
        return HttpResponseForbidden("You are not authorized to view this page.")

    # 2) Handle POST actions (reassign or SMS)
    if request.method == 'POST':
        action_type = request.POST.get('action_type', '')
        customer_id = request.POST.get('customer_id', '')
        if not customer_id:
            messages.error(request, "No customer specified.")
            return redirect('manage_customers')
        customer = get_object_or_404(Customer, id=customer_id)

        if action_type == 'change_branch':
            # only staff/superuser can reassign to any branch
            if not (user.is_staff or user.is_superuser):
                return HttpResponseForbidden("Cannot change branch.")
            new_branch_id = request.POST.get('new_branch_id', '')
            if new_branch_id:
                new_branch = get_object_or_404(Branch, id=new_branch_id)
                customer.branch = new_branch
                customer.save()
                messages.success(request,
                                 f"{customer.user.get_full_name()} was reassigned to {new_branch.name}.")
            else:
                messages.error(request, "No branch selected for reassignment.")

        elif action_type == 'send_sms':
            phone_number = customer.user.phone_number
            if not phone_number:
                messages.warning(request, "Customer has no phone number.")
            else:
                sms_message = request.POST.get('sms_message', '').strip()
                if sms_message:
                    try:
                        send_sms(phone_number, sms_message)
                        messages.success(request, f"SMS sent to {phone_number}.")
                    except Exception as e:
                        messages.error(request, f"Failed to send SMS: {e}")
                else:
                    messages.error(request, "SMS message is empty.")

        return redirect('manage_customers')

    # 3) Render
    context = {
        'customers': customers_qs.order_by('user__first_name'),
        'branches': branches,
        'selected_branch_id': str(selected_branch_id),
        'hide_branch_selector': hide_branch_selector,
    }
    return render(request, 'layouts/admin/manage_customers.html', context)


@staff_or_branch_admin_required
def customer_detail_admin(request, customer_id):
    """
    Admin view to see details of a specific customer, including vehicles,
    service orders, loyalty transactions, subscription trails, and the latest renewal trail.
    Also provides options to enroll/renew the customer on a subscription.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    vehicles = CustomerVehicle.objects.filter(customer=customer)
    service_orders = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')

    # Get loyalty transactions sorted from latest to oldest
    loyalty_transactions = customer.loyalty_transactions.all().order_by('-date')
    # Get subscription trails for this customer, latest first
    from .models import CustomerSubscriptionTrail, CustomerSubscriptionRenewalTrail
    subscription_trails = CustomerSubscriptionTrail.objects.filter(customer=customer).order_by('-date_used')
    # Get the latest subscription renewal trail (if any)
    latest_renewal = CustomerSubscriptionRenewalTrail.objects.filter(customer=customer).order_by(
        '-date_renewed').first()
    latest_subscription = CustomerSubscription.objects.filter(customer=customer).order_by('-start_date').first()

    context = {
        'customer': customer,
        'vehicles': vehicles,
        'service_orders': service_orders,
        'loyalty_transactions': loyalty_transactions,
        'subscription_trails': subscription_trails,
        'latest_renewal': latest_renewal,
        'latest_subscription': latest_subscription,
    }
    return render(request, 'layouts/admin/customer_detail_admin.html', context)


@staff_member_required
def vehicle_groups(request):
    """
    Admin view to list all vehicle groups.
    """
    vgroups = VehicleGroup.objects.all()
    return render(request, 'layouts/admin/vehicle_groups.html', {'vehicle_groups': vgroups})


@staff_member_required
def manage_branches(request):
    """
    Admin view to see, edit, or delete branches.
    """
    branches = Branch.objects.all()
    return render(request, 'layouts/admin/manage_branches.html', {'branches': branches})


@staff_member_required
def add_branch(request):
    """
    Add a new branch.
    """
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Branch added successfully.')
            return redirect('manage_branches')
    else:
        form = BranchForm()

    return render(request, 'layouts/admin/add_branch.html', {'form': form})


@staff_member_required
def edit_branch(request, branch_id):
    """
    Edit a branch and optionally reassign the branch head.
    """
    branch = get_object_or_404(Branch, id=branch_id)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            branch = form.save()

            # Handle branch head assignment
            branch_head_id = request.POST.get('branch_head')
            if branch_head_id:
                # Unassign previous branch head
                Worker.objects.filter(branch=branch, is_branch_head=True).update(is_branch_head=False)
                # Assign new branch head
                branch_head = get_object_or_404(Worker, id=branch_head_id)
                branch_head.is_branch_head = True
                branch_head.save()

            messages.success(request, 'Branch updated successfully.')
            return redirect('manage_branches')
    else:
        form = BranchForm(instance=branch)

    workers = Worker.objects.filter(branch=branch)
    branch_head = workers.filter(is_branch_head=True).first()

    context = {
        'form': form,
        'branch': branch,
        'workers': workers,
        'branch_head': branch_head,
    }
    return render(request, 'layouts/admin/edit_branch.html', context)


@staff_member_required
def delete_branch(request, branch_id):
    """
    Delete a branch (confirmation).
    """
    branch = get_object_or_404(Branch, id=branch_id)
    if request.method == 'POST':
        branch.delete()
        messages.success(request, 'Branch deleted successfully.')
        return redirect('manage_branches')
    return render(request, 'layouts/admin/delete_branch.html', {'branch': branch})


@staff_member_required
def branch_insights(request, branch_id):
    """
    Detailed insights for a single branch over 'week' or 'month':
    - Services & revenue per day
    - Customers & vehicles added
    - Worker count & average rating
    """
    branch = get_object_or_404(Branch, id=branch_id)
    time_period = request.GET.get('time_period', 'week')
    today = timezone.now().date()

    if time_period == 'month':
        start_date = today.replace(day=1)
    else:
        start_date = today - timedelta(days=today.weekday())
    end_date = today

    date_list = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    num_days = (end_date - start_date).days + 1

    services_data = []
    revenue_data = []
    dates = []
    has_data = False

    for date_item in date_list:
        daily_services_count = ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date=date_item
        ).count()
        daily_revenue_total = ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date=date_item
        ).aggregate(total=Sum('final_amount'))['total'] or 0

        services_data.append(daily_services_count)
        revenue_data.append(daily_revenue_total)
        dates.append(date_item.strftime('%Y-%m-%d'))

        if daily_services_count > 0 or daily_revenue_total > 0:
            has_data = True

    # Average customers added
    customers = Customer.objects.filter(
        date_joined_app__gte=start_date,
        date_joined_app__lte=end_date
    )
    total_customers = customers.count()
    avg_customers_per_day = round(total_customers / num_days) if num_days else 0

    # Average vehicles added
    vehicles = CustomerVehicle.objects.filter(
        date_added__gte=start_date,
        date_added__lte=end_date
    )
    total_vehicles = vehicles.count()
    avg_vehicles_per_day = round(total_vehicles / num_days) if num_days else 0

    # Worker count & average rating
    num_workers = Worker.objects.filter(branch=branch).count()
    avg_worker_rating = Worker.objects.filter(
        branch=branch
    ).aggregate(avg_rating=Avg('servicerenderedorder__customer_rating'))['avg_rating'] or 0

    context = {
        'branch': branch,
        'time_period': time_period,
        'dates': dates,
        'services_data': services_data,
        'revenue_data': revenue_data,
        'has_data': has_data,
        'avg_customers_per_day': avg_customers_per_day,
        'avg_vehicles_per_day': avg_vehicles_per_day,
        'num_workers': num_workers,
        'avg_worker_rating': avg_worker_rating,
    }
    return render(request, 'layouts/admin/branch_insights.html', context)


def daily_profit_loss(branch, date):
    """
    Utility function to get daily profit or loss for a branch by date.
    """
    total_revenue = Revenue.objects.filter(branch=branch, date=date).aggregate(
        total=Sum('final_amount')
    )['total'] or 0
    total_expenses = Expense.objects.filter(branch=branch, date=date).aggregate(
        total=Sum('amount')
    )['total'] or 0
    return total_revenue - total_expenses


@staff_member_required
def analytics_dashboard(request):
    """
    Displays a dashboard for monthly analytics:
    - Revenue vs Expenses over the selected month
    - Services rendered per branch
    - Products sold
    - New vehicles
    """
    selected_month = request.GET.get('month')
    selected_year = request.GET.get('year')
    today = timezone.now().date()
    current_year = today.year
    current_month = today.month

    months = [
        {'num': 1, 'name': 'January'},
        {'num': 2, 'name': 'February'},
        {'num': 3, 'name': 'March'},
        {'num': 4, 'name': 'April'},
        {'num': 5, 'name': 'May'},
        {'num': 6, 'name': 'June'},
        {'num': 7, 'name': 'July'},
        {'num': 8, 'name': 'August'},
        {'num': 9, 'name': 'September'},
        {'num': 10, 'name': 'October'},
        {'num': 11, 'name': 'November'},
        {'num': 12, 'name': 'December'},
    ]

    start_year = 2020
    years = list(range(start_year, current_year + 1))

    if selected_month and selected_year:
        try:
            selected_month = int(selected_month)
            selected_year = int(selected_year)
            start_date = datetime(selected_year, selected_month, 1).date()
            if selected_month == 12:
                end_date = datetime(selected_year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(selected_year, selected_month + 1, 1).date() - timedelta(days=1)
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today

    try:
        admin_account = request.user.admin_profile
        daily_budget = admin_account.daily_expense_amount
    except models.AdminAccount.DoesNotExist:
        daily_budget = 0

    # Revenue data
    revenue_data = Revenue.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name', 'date').annotate(total_revenue=Sum('final_amount'))

    # Expenses data
    expenses_data = Expense.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name', 'date').annotate(total_expense=Sum('amount'))

    # Services data (count of completed orders)
    services_data = ServiceRenderedOrder.objects.filter(
        branch__isnull=False,
        status='completed',
        date__date__gte=start_date,
        date__date__lte=end_date
    ).values('branch__name').annotate(total_services=Count('id'))

    # Products sold
    products_sold_data = ProductPurchased.objects.filter(
        service_order__branch__isnull=False,
        service_order__date__date__gte=start_date,
        service_order__date__date__lte=end_date
    ).values('product__name').annotate(total_quantity=Sum('quantity'))

    # New vehicles
    new_vehicles_data = CustomerVehicle.objects.filter(
        date_added__date__gte=start_date,
        date_added__date__lte=end_date
    ).annotate(
        date_added_only=TruncDate('date_added')
    ).values('date_added_only').annotate(total=Count('id')).order_by('date_added_only')

    # Prepare data for daily charts
    date_counts = {}
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        date_counts[date_str] = {'revenue': 0, 'expense': 0}
        current_date += timedelta(days=1)

    for entry in revenue_data:
        date_str = entry['date'].strftime('%Y-%m-%d')
        if date_str in date_counts:
            date_counts[date_str]['revenue'] += entry['total_revenue']

    for entry in expenses_data:
        date_str = entry['date'].strftime('%Y-%m-%d')
        if date_str in date_counts:
            date_counts[date_str]['expense'] += entry['total_expense']

    dates = sorted(date_counts.keys())
    revenues = [date_counts[d]['revenue'] for d in dates]
    expenses = [date_counts[d]['expense'] for d in dates]

    # Vehicles added
    new_vehicles_dict = {
        entry['date_added_only'].strftime('%Y-%m-%d'): entry['total']
        for entry in new_vehicles_data
    }
    new_vehicles = [new_vehicles_dict.get(d, 0) for d in dates]

    # Services per branch
    services_branch_names = [s['branch__name'] for s in services_data]
    services_total_services = [s['total_services'] for s in services_data]

    # Products sold
    products_sold_labels = [p['product__name'] for p in products_sold_data]
    products_sold_values = [p['total_quantity'] for p in products_sold_data]

    context = {
        'months': months,
        'years': years,
        'selected_year': selected_year if (selected_month and selected_year) else current_year,
        'selected_month': selected_month if (selected_month and selected_year) else current_month,
        'daily_budget': daily_budget,
        'dates': dates,
        'revenues': revenues,
        'expenses': expenses,
        'services_branch_names': services_branch_names,
        'services_total_services': services_total_services,
        'products_sold_labels': products_sold_labels,
        'products_sold_values': products_sold_values,
        'new_vehicles_data': new_vehicles,
    }
    return render(request, 'layouts/admin/analytics_dashboard.html', context)


@staff_member_required()
def api_revenue_expenses(request):
    """
    AJAX endpoint for retrieving revenue and expense data per branch
    for the selected month/year. Used in analytics dashboard charts.
    """
    selected_month = request.GET.get('month')
    selected_year = request.GET.get('year')

    today = timezone.now().date()
    current_year = today.year

    if selected_month and selected_year:
        try:
            selected_month = int(selected_month)
            selected_year = int(selected_year)
            start_date = datetime(selected_year, selected_month, 1).date()
            if selected_month == 12:
                end_date = datetime(selected_year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(selected_year, selected_month + 1, 1).date() - timedelta(days=1)
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today

    revenue_data = Revenue.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name').annotate(total_revenue=Sum('final_amount'))

    expenses_data = Expense.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name').annotate(total_expense=Sum('amount'))

    revenue_dict = {r['branch__name']: r['total_revenue'] for r in revenue_data}
    expenses_dict = {e['branch__name']: e['total_expense'] for e in expenses_data}

    branches = Branch.objects.all()
    branch_names = []
    branch_revenues = []
    branch_expenses = []

    for branch in branches:
        branch_names.append(branch.name)
        branch_revenues.append(revenue_dict.get(branch.name, 0))
        branch_expenses.append(expenses_dict.get(branch.name, 0))

    data = {
        'branch_names': branch_names,
        'branch_revenues': branch_revenues,
        'branch_expenses': branch_expenses,
    }
    return JsonResponse(data)


@login_required(login_url='login')
def expense_list(request):
    """
    Shows a list of expenses.
    - Admin/staff: can filter by branch (if multiple branches).
    - Worker: sees only their branch's expenses, no branch filter shown.
    """
    user = request.user

    # If user is admin/staff => allow branch filter
    if user.is_staff or user.is_superuser:
        branches = Branch.objects.all()
        selected_branch_id = request.GET.get('branch', '')

        expense_qs = Expense.objects.all().order_by('-date')
        if selected_branch_id:
            expense_qs = expense_qs.filter(branch_id=selected_branch_id)

        expenses = expense_qs
    else:
        # Worker => only their single branch, no branch filter
        try:
            worker = user.worker_profile
        except Worker.DoesNotExist:
            messages.error(request, 'You are not authorized to view this page.')
            return redirect('index')

        branches = None
        selected_branch_id = None
        expenses = Expense.objects.filter(branch=worker.branch).order_by('-date')

    context = {
        'expenses': expenses,
        'branches': branches,
        'selected_branch_id': selected_branch_id
    }
    return render(request, 'layouts/expense_list.html', context)


@login_required(login_url='login')
def add_expense(request):
    """
    Add a new expense entry. If the user is a worker, it’s automatically assigned
    to their branch. If the user is admin, they can select a branch.
    """
    user = request.user
    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = user
            expense.save()
            messages.success(request, 'Expense added successfully.')
            return redirect('expense_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ExpenseForm(user=user)

    return render(request, 'layouts/add_expense.html', {'form': form})


@login_required(login_url='login')
def edit_expense(request, pk):
    """
    Edit an existing expense. Non-admin users can only edit if they created it.
    """
    expense = get_object_or_404(Expense, pk=pk)
    user = request.user

    # Only admin or the creator can edit
    if not user.is_staff and not user.is_superuser and expense.user != user:
        messages.error(request, 'You are not authorized to edit this expense.')
        return redirect('expense_list')

    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense, user=user)
        if form.is_valid():
            updated_expense = form.save(commit=False)
            updated_expense.user = user
            updated_expense.save()
            messages.success(request, 'Expense updated successfully.')
            return redirect('expense_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ExpenseForm(instance=expense, user=user)

    return render(request, 'layouts/edit_expense.html', {'form': form, 'expense': expense})


@login_required(login_url='login')
def delete_expense(request, pk):
    """
    Delete an expense. Non-admin users can only delete their own expenses.
    """
    expense = get_object_or_404(Expense, pk=pk)
    user = request.user

    if not user.is_staff and not user.is_superuser and expense.user != user:
        messages.error(request, 'You are not authorized to delete this expense.')
        return redirect('expense_list')

    if request.method == 'POST':
        expense.delete()
        messages.success(request, 'Expense deleted successfully.')
        return redirect('expense_list')

    return render(request, 'layouts/delete_expense.html', {'expense': expense})


@staff_or_branch_admin_required
def commissions_by_date(request):
    from datetime import datetime as dt, timedelta
    """
    Show per-worker commission for a single day (+ services & vehicles count),
    allow inline bonus / deduction editing, and display column totals.
    """
    # ─── 1. Parse GET params ─────────────────────────────────────────────
    branches = Branch.objects.all()

    branch_id = request.GET.get("branch") or ""
    worker_id = request.GET.get("worker") or ""
    date_str = request.GET.get("date") or ""

    # validated objects (or None)
    branch_obj = Branch.objects.filter(id=branch_id).first() if branch_id else None
    worker_obj = Worker.objects.filter(id=worker_id).first() if worker_id else None

    try:
        selected_date = dt.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        selected_date = timezone.localdate()
        if date_str:
            messages.error(request, "Invalid date format, defaulted to today.")

    # ─── 2. Persist bonus / deductions if POST ───────────────────────────
    if request.method == "POST":
        with transaction.atomic():
            for key, val in request.POST.items():
                if not (key.startswith("deduction_") or key.startswith("bonus_")):
                    continue
                try:
                    wid = int(key.split("_")[1])
                    amount = float(val or 0)
                except (ValueError, IndexError):
                    continue

                adj, _ = WorkerDailyAdjustment.objects.get_or_create(
                    worker_id=wid,
                    date=selected_date,
                    defaults={"branch": branch_obj},
                )
                if key.startswith("deduction_"):
                    if adj.deduction != amount:
                        adj.deduction = amount
                        adj.save(update_fields=["deduction"])
                else:  # bonus
                    if adj.bonus != amount:
                        adj.bonus = amount
                        adj.save(update_fields=["bonus"])

        messages.success(request, "Adjustments saved.")
        qs = f"?date={selected_date}&branch={branch_id}&worker={worker_id}"
        return redirect(request.path + qs)

    # ─── 3. Core commission queryset ─────────────────────────────────────
    comm_qs = Commission.objects.filter(date=selected_date)
    if branch_obj:
        comm_qs = comm_qs.filter(worker__branch=branch_obj)
    if worker_obj:
        comm_qs = comm_qs.filter(worker=worker_obj)

    # aggregate per worker
    agg = (
        comm_qs.values("worker")
        .annotate(
            total_commission=Sum("amount"),
            num_services=Count("service_rendered_id", distinct=True),
            num_vehicles=Count("service_rendered__order__vehicle_id", distinct=True),
        )
    )

    # ─── 4.  Ensure adjustment rows exist & fetch in bulk ────────────────
    worker_ids = [row["worker"] for row in agg]
    # get_or_create in bulk-ish (one DB round-trip per missing worker)
    for wid in worker_ids:
        WorkerDailyAdjustment.objects.get_or_create(
            worker_id=wid,
            date=selected_date,
            defaults={"branch": branch_obj},
        )
    # pull all adjustments for selected date in one query
    adjustments = {
        adj.worker_id: adj
        for adj in WorkerDailyAdjustment.objects.filter(
            worker_id__in=worker_ids, date=selected_date
        )
    }

    # pull workers (with user) in one hit
    workers_map = {
        w.id: w
        for w in Worker.objects.filter(id__in=worker_ids).select_related("user")
    }

    # ─── 5. Build result rows & totals ────────────────────────────────────
    results = []
    totals = {
        "services": 0, "vehicles": 0,
        "commission": 0, "bonus": 0,
        "deduction": 0, "earnings": 0,
    }

    for row in agg:
        wid = row["worker"]
        w = workers_map[wid]
        adj = adjustments.get(wid)

        total_comm = row["total_commission"] or 0
        bonus = adj.bonus if adj else 0
        deduct = adj.deduction if adj else 0
        earnings = total_comm - deduct + bonus

        results.append({
            "worker": w,
            "position": w.position or "-",
            "num_services": row["num_services"],
            "num_vehicles": row["num_vehicles"],
            "total_commission": total_comm,
            "bonus": bonus,
            "deduction": deduct,
            "total_earnings": earnings,
        })

        totals["services"] += row["num_services"]
        totals["vehicles"] += row["num_vehicles"]
        totals["commission"] += total_comm
        totals["bonus"] += bonus
        totals["deduction"] += deduct
        totals["earnings"] += earnings

    # worker dropdown limited by branch when selected
    worker_choices = (
        Worker.objects.filter(branch=branch_obj) if branch_obj
        else Worker.objects.all()
    )

    hide_branch_selector = (
            getattr(request.user, "worker_profile", None)
            and request.user.worker_profile.is_branch_admin
    )

    return render(
        request,
        "layouts/commissions_by_date.html",
        {
            "branches": branches,
            "selected_branch_id": branch_id,
            "workers": worker_choices,
            "selected_worker_id": worker_id,
            "selected_date": selected_date,
            "hide_branch_selector": hide_branch_selector,
            "commissions": results,
            "tot_services": totals["services"],
            "tot_vehicles": totals["vehicles"],
            "tot_commission": totals["commission"],
            "tot_bonus": totals["bonus"],
            "tot_deduction": totals["deduction"],
            "tot_earnings": totals["earnings"],
        },
    )


@staff_or_branch_admin_required
def commission_breakdown(request):
    """
    AJAX endpoint to get the breakdown of commissions for a given worker on a given date.
    GET params:
      - worker_id
      - date (YYYY-MM-DD)
    Returns JSON: { success: True, commissions: [ { service, vehicle, amount, order_number }... ] }
    """
    worker_id = request.GET.get('worker_id')
    date_str = request.GET.get('date')

    # 1) parse date
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)

    # 2) lookup worker
    worker = get_object_or_404(Worker, id=worker_id)

    # 3) fetch commissions newest-first
    commissions = (
        Commission.objects
        .filter(worker=worker, date=date_obj)
        .select_related('service_rendered__service', 'service_rendered__order__vehicle')
        .order_by('-date', '-id')
    )

    # 4) build JSON
    data = []
    for c in commissions:
        service_name = ''
        vehicle_info = 'No Vehicle'
        if c.service_rendered and c.service_rendered.service:
            service_name = c.service_rendered.service.service_type

        ord = c.service_rendered.order if c.service_rendered else None
        if ord and ord.vehicle:
            v = ord.vehicle
            vehicle_info = f"{v.car_make} - {v.car_plate}"

        data.append({
            'service': service_name,
            'vehicle': vehicle_info,
            'amount': float(c.amount),
            'order_number': ord.service_order_number if ord else '',
        })

    return JsonResponse({'success': True, 'commissions': data})


@staff_or_branch_admin_required
def expenses_by_date(request):
    """
    Page where admin can pick a single date (and optionally a branch)
    to see all expenses for that date.
    """
    branches = Branch.objects.all()
    selected_branch_id = request.GET.get('branch', '')
    selected_date_str = request.GET.get('date', '')

    # Default to today's date if none provided
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
            messages.error(request, "Invalid date format. Showing today's data.")
    else:
        selected_date = timezone.now().date()

    expenses_qs = Expense.objects.filter(date=selected_date)

    if selected_branch_id:
        expenses_qs = expenses_qs.filter(branch_id=selected_branch_id)

    total_expenses = expenses_qs.aggregate(total=Sum('amount'))['total'] or 0

    hide_branch_selector = (
            hasattr(request.user, 'worker_profile')
            and request.user.worker_profile.is_branch_admin
    )
    if hide_branch_selector:
        # automatically filter expenses_qs by request.user.worker_profile.branch
        expenses_qs = expenses_qs.filter(branch=request.user.worker_profile.branch)

    context = {
        'hide_branch_selector': hide_branch_selector,
        'branches': branches,
        'selected_branch_id': selected_branch_id,
        'selected_date': selected_date,
        'expenses': expenses_qs,
        'total_expenses': total_expenses,
    }
    return render(request, 'layouts/expenses_by_date.html', context)


def _user_is_branch_admin(user):
    try:
        return user.worker_profile.is_branch_admin
    except Worker.DoesNotExist:
        return False


@staff_or_branch_admin_required
def financial_overview(request):
    """
    A comprehensive financial overview that supports filtering by:
    - Date range,
    - Month & year,
    - or Week.
    Staff/superusers can optionally filter by branch.
    Branch-admins see only their branch and do not get a branch dropdown.
    """
    user = request.user
    is_branch_admin = _user_is_branch_admin(user)
    hide_branch_selector = is_branch_admin  # if True, template will omit branch dropdown

    # Build list of possible branches (for staff only)
    branches = Branch.objects.all()

    # If branch admin => force their branch
    if is_branch_admin:
        worker = user.worker_profile
        selected_branch_id = worker.branch.id
    else:
        selected_branch_id = request.GET.get('branch', '')

    # Common filters
    view_type = request.GET.get('view_type', 'date_range')  # 'date_range' | 'month_year' | 'week'
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    month_str = request.GET.get('month', '')
    year_str = request.GET.get('year', '')
    week_str = request.GET.get('week', '')

    today = timezone.now().date()
    start_date = today
    end_date = today

    # Determine start_date / end_date
    if view_type == 'month_year':
        try:
            m = int(month_str);
            y = int(year_str)
            start_date = datetime(y, m, 1).date()
            end_date = (datetime(y + (m == 12), (m % 12) + 1, 1).date() - timedelta(days=1))
        except (ValueError, TypeError):
            messages.error(request, "Invalid month/year; defaulting to this month.")
            start_date = today.replace(day=1)
            end_date = today

    elif view_type == 'week':
        try:
            wk = int(week_str)
            # first Monday of the year
            first = datetime(today.year, 1, 1).date()
            while first.isoweekday() != 1:
                first += timedelta(days=1)
            start_date = first + timedelta(weeks=wk - 1)
            end_date = start_date + timedelta(days=6)
        except (ValueError, TypeError):
            messages.error(request, "Invalid week; defaulting to current week.")
            weekday = today.isoweekday()
            start_date = today - timedelta(days=weekday - 1)
            end_date = start_date + timedelta(days=6)

    else:  # date_range
        try:
            if start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            else:
                start_date = today
                end_date = today
        except ValueError:
            messages.error(request, "Invalid date range; showing today.")
            start_date = today
            end_date = today

    if start_date > end_date:
        messages.warning(request, "Start date after end date; swapping.")
        start_date, end_date = end_date, start_date

    # Base querysets
    revenue_qs = Revenue.objects.filter(date__range=[start_date, end_date])
    expense_qs = Expense.objects.filter(date__range=[start_date, end_date])
    commission_qs = Commission.objects.filter(date__range=[start_date, end_date])
    arrears_qs = Arrears.objects.filter(
        date_created__date__gte=start_date,
        date_created__date__lte=end_date
    )

    # Apply branch filter if any
    if selected_branch_id:
        revenue_qs = revenue_qs.filter(branch_id=selected_branch_id)
        expense_qs = expense_qs.filter(branch_id=selected_branch_id)
        commission_qs = commission_qs.filter(worker__branch_id=selected_branch_id)
        arrears_qs = arrears_qs.filter(branch_id=selected_branch_id)

    # Summaries
    total_revenue = revenue_qs.aggregate(total=Sum('final_amount'))['total'] or 0
    total_expenses = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_commissions = commission_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_arrears = arrears_qs.aggregate(total=Sum('amount_owed'))['total'] or 0

    # Build daily series
    daily_data = {}
    d = start_date
    while d <= end_date:
        daily_data[d] = {'revenue': 0, 'expense': 0, 'commission': 0, 'arrears': 0, 'net': 0}
        d += timedelta(days=1)

    for e in revenue_qs.values('date').annotate(sum_rev=Sum('final_amount')):
        daily_data[e['date']]['revenue'] = float(e['sum_rev'] or 0)
    for e in expense_qs.values('date').annotate(sum_exp=Sum('amount')):
        daily_data[e['date']]['expense'] = float(e['sum_exp'] or 0)
    for e in commission_qs.values('date').annotate(sum_com=Sum('amount')):
        daily_data[e['date']]['commission'] = float(e['sum_com'] or 0)
    for arr in arrears_qs:
        dd = arr.date_created.date()
        if dd in daily_data:
            daily_data[dd]['arrears'] += float(arr.amount_owed or 0)
    # compute net
    for dd, vals in daily_data.items():
        vals['net'] = vals['revenue'] - vals['expense']

    # Prepare for chart & table
    sorted_days = sorted(daily_data)
    chart_labels = [d.strftime("%Y-%m-%d") for d in sorted_days]
    chart_revenues = [daily_data[d]['revenue'] for d in sorted_days]
    chart_expenses = [daily_data[d]['expense'] for d in sorted_days]
    chart_commissions = [daily_data[d]['commission'] for d in sorted_days]
    chart_arrears = [daily_data[d]['arrears'] for d in sorted_days]
    chart_nets = [daily_data[d]['net'] for d in sorted_days]

    daily_data_list = [
        {'date': d.strftime("%Y-%m-%d"),
         'revenue': daily_data[d]['revenue'],
         'expense': daily_data[d]['expense'],
         'net': daily_data[d]['net']}
        for d in sorted_days
    ]

    context = {
        'branches': branches,
        'hide_branch_selector': hide_branch_selector,
        'selected_branch_id': selected_branch_id,
        'view_type': view_type,
        'start_date': start_date,
        'end_date': end_date,
        'month': month_str,
        'year': year_str,
        'week': week_str,

        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_commissions': total_commissions,
        'total_arrears': total_arrears,

        'daily_data_list': daily_data_list,
        'months': [
            (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
            (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
            (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
        ],

        'chart_labels_json': json.dumps(chart_labels),
        'chart_revenues_json': json.dumps(chart_revenues),
        'chart_expenses_json': json.dumps(chart_expenses),
        'chart_commissions_json': json.dumps(chart_commissions),
        'chart_arrears_json': json.dumps(chart_arrears),
        'chart_nets_json': json.dumps(chart_nets),
    }
    return render(request, 'layouts/financial_overview.html', context)


from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Value
from datetime import date
from django.contrib import messages

from .models import ProductSale, ProductCategory


@staff_or_branch_admin_required
def product_sales_report(request):
    """
    Shows a product sales report with filters for date/month/year,
    plus branch & category filters. Branch-admins see only their branch
    (no branch dropdown); staff see all branches.
    """
    user = request.user
    is_branch_admin = _user_is_branch_admin(user)
    hide_branch_selector = is_branch_admin

    # All branches & categories for staff
    branches = Branch.objects.all()
    categories = ProductCategory.objects.all()

    # Determine branch filter
    if is_branch_admin:
        branch_id = user.worker_profile.branch.id
    else:
        branch_id = request.GET.get('branch', '')

    # Category filter
    category_id = request.GET.get('category', '')

    # Date filters
    date_str = request.GET.get('date', '')
    month_str = request.GET.get('month', '')
    year_str = request.GET.get('year', '')

    # Start building queryset
    sales_qs = ProductSale.objects.all()

    # Branch filter
    if branch_id:
        sales_qs = sales_qs.filter(branch_id=branch_id)

    # Category filter
    if category_id:
        sales_qs = sales_qs.filter(product__category_id=category_id)

    # Date / month-year / year
    selected_date = None
    selected_month = None
    selected_year = None

    try:
        if date_str:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            sales_qs = sales_qs.filter(date_sold__date=selected_date)
        elif month_str and year_str:
            selected_month = int(month_str)
            selected_year = int(year_str)
            sales_qs = sales_qs.filter(
                date_sold__year=selected_year,
                date_sold__month=selected_month
            )
        elif year_str:
            selected_year = int(year_str)
            sales_qs = sales_qs.filter(date_sold__year=selected_year)
        else:
            # default to today
            selected_date = timezone.now().date()
            sales_qs = sales_qs.filter(date_sold__date=selected_date)
    except ValueError:
        messages.error(request, "Invalid date/month/year; defaulting to today.")
        selected_date = timezone.now().date()
        sales_qs = sales_qs.filter(date_sold__date=selected_date)

    # Annotate cost & profit
    sales_qs = sales_qs.annotate(
        line_cost=F('product__cost') * F('quantity'),
        line_profit=(F('product__price') - F('product__cost')) * F('quantity'),
    )

    # Totals
    total_revenue = sales_qs.aggregate(sum_rev=Sum('total_price'))['sum_rev'] or 0
    total_cost = sales_qs.aggregate(sum_cost=Sum('line_cost'))['sum_cost'] or 0
    total_profit = sales_qs.aggregate(sum_profit=Sum('line_profit'))['sum_profit'] or 0

    # Category breakdown
    cat_data_qs = sales_qs.values('product__category__name').annotate(
        cat_revenue=Sum('total_price'),
        cat_profit=Sum('line_profit')
    )
    chart_labels = []
    chart_revenue_data = []
    chart_profit_data = []
    for row in cat_data_qs:
        name = row['product__category__name'] or "Uncategorized"
        chart_labels.append(name)
        chart_revenue_data.append(float(row['cat_revenue'] or 0))
        chart_profit_data.append(float(row['cat_profit'] or 0))

    # Stock summary
    stock_qs = Product.objects.values('category__name').annotate(
        in_stock_qty=Sum(F('stock')),
        total_cost_if_sold=Sum(F('stock') * F('cost')),
        total_price_if_sold=Sum(F('stock') * F('price')),
        total_profit_if_sold=Sum((F('price') - F('cost')) * F('stock')),
    ).order_by('category__name')

    stock_summary = []
    for row in stock_qs:
        cat = row['category__name'] or "Uncategorized"
        stock_summary.append({
            'category_name': cat,
            'in_stock_qty': row['in_stock_qty'] or 0,
            'total_cost_if_sold': row['total_cost_if_sold'] or 0.0,
            'total_price_if_sold': row['total_price_if_sold'] or 0.0,
            'total_profit_if_sold': row['total_profit_if_sold'] or 0.0,
        })

    months = list(range(1, 13))

    context = {
        'months': months,
        'branches': branches,
        'categories': categories,
        'hide_branch_selector': hide_branch_selector,
        'selected_branch_id': branch_id,
        'selected_category_id': category_id,

        'date_str': date_str,
        'month_str': month_str,
        'year_str': year_str,
        'selected_date': selected_date,
        'selected_month': selected_month,
        'selected_year': selected_year,

        'sales': sales_qs,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_profit': total_profit,

        # chart
        'chart_labels': json.dumps(chart_labels),
        'chart_revenue_data': chart_revenue_data,
        'chart_profit_data': chart_profit_data,

        'stock_summary': stock_summary,
    }
    return render(request, 'layouts/product_sales_report.html', context)


@login_required(login_url='login')
def arrears_list(request):
    """
    Shows a list of Arrears with optional filters:
      - For staff/admin: filter by Branch, date range, paid status
      - For workers: only show their branch's arrears, no branch filter.
    """
    user = request.user

    # If user is staff/superuser => can see all branches
    # Otherwise => must get worker's branch
    if user.is_staff or user.is_superuser:
        branches = Branch.objects.all()
        branch_id = request.GET.get('branch', '')
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')
        paid_filter = request.GET.get('paid_filter', 'all')
        arrears_qs = Arrears.objects.all().order_by('-date_created')

        # Branch filter
        if branch_id:
            arrears_qs = arrears_qs.filter(branch_id=branch_id)

        # Date range filter
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                arrears_qs = arrears_qs.filter(date_created__date__range=[start_date, end_date])
            except ValueError:
                messages.warning(request, "Invalid date range. Ignoring date filters.")

        # Paid filter
        if paid_filter == 'paid':
            arrears_qs = arrears_qs.filter(is_paid=True)
        elif paid_filter == 'unpaid':
            arrears_qs = arrears_qs.filter(is_paid=False)

        total_owed = arrears_qs.aggregate(total=Sum('amount_owed'))['total'] or 0

        context = {
            'branches': branches,
            'branch_id': branch_id,
            'start_date_str': start_date_str,
            'end_date_str': end_date_str,
            'paid_filter': paid_filter,
            'arrears_list': arrears_qs,
            'total_owed': total_owed,
            'is_staff_view': True,  # For template conditionals
        }
        return render(request, 'layouts/admin/arrears_list.html', context)

    else:
        # Worker flow
        try:
            worker = Worker.objects.get(user=user)
        except Worker.DoesNotExist:
            messages.error(request, "No worker profile found.")
            return redirect('index')

        # Only see arrears for that worker's branch
        arrears_qs = Arrears.objects.filter(branch=worker.branch).order_by('-date_created')

        # Optionally filter by paid/unpaid if you want
        # For simplicity, let's show all (or you can do the same paid_filter logic)
        paid_filter = request.GET.get('paid_filter', 'all')
        if paid_filter == 'paid':
            arrears_qs = arrears_qs.filter(is_paid=True)
        elif paid_filter == 'unpaid':
            arrears_qs = arrears_qs.filter(is_paid=False)

        total_owed = arrears_qs.aggregate(total=Sum('amount_owed'))['total'] or 0

        context = {
            'arrears_list': arrears_qs,
            'total_owed': total_owed,
            'is_staff_view': False,  # For template conditionals
            'paid_filter': paid_filter,
        }
        return render(request, 'layouts/arrears_list.html', context)


@login_required(login_url='login')
def mark_arrears_as_paid(request, arrears_id):
    """
    Marks the given Arrears record as paid.
    - Sets is_paid=True, date_paid=now
    - Creates a Revenue record for the current date with amount=arrears.amount_owed
    - Sends an SMS to the customer indicating the arrears are cleared.
    - Only workers from the same branch or staff can mark it as paid.
    """
    arrears = get_object_or_404(Arrears, id=arrears_id)
    user = request.user

    # Security check: if user is not staff/admin, they must be a worker in the same branch.
    if not user.is_staff and not user.is_superuser:
        try:
            worker = user.worker_profile
        except Worker.DoesNotExist:
            messages.error(request, "You do not have permission to mark arrears as paid.")
            return redirect('index')

        if worker.branch != arrears.branch:
            messages.error(request, "You cannot mark arrears in another branch as paid.")
            return redirect('arrears_list')

    # If it's already paid, do nothing.
    if arrears.is_paid:
        messages.info(request, "This arrears is already marked as paid.")
        return redirect('arrears_list')

    # Mark as paid
    arrears.is_paid = True
    arrears.date_paid = timezone.now()
    arrears.save()

    # Create a Revenue record for the day it's paid
    Revenue.objects.create(
        service_rendered=arrears.service_order,  # Optionally link back to the ServiceRenderedOrder
        branch=arrears.branch,
        amount=arrears.amount_owed,
        final_amount=arrears.amount_owed,
        user=user,
        date=timezone.now().date(),
    )

    # Send an SMS to the customer if a phone number is available
    service_order = arrears.service_order
    service_order.status = "completed"
    service_order.save()
    if service_order and service_order.customer and service_order.customer.user.phone_number:
        phone_number = service_order.customer.user.phone_number
        # Customize your message text as needed
        message_text = (
            f"Hello {service_order.customer.user.first_name}, "
            f"your on-credit service (Order #{service_order.service_order_number}) for GHS {arrears.amount_owed:.2f} has now been fully paid."
            "Thank you for clearing your balance!"
        )
        try:
            send_sms(phone_number, message_text)
        except Exception as sms_exc:
            messages.warning(request, f"Arrears paid, but SMS could not be sent: {sms_exc}")

    messages.success(request, "Arrears has been marked as paid, revenue recorded, and SMS notification sent.")
    return redirect('arrears_list')


@login_required(login_url='login')
def arrears_details(request, arrears_id):
    """
    Returns JSON details about the ServiceRenderedOrder tied to this Arrears.
    Includes services, workers, vehicle, etc.
    """
    arrears = get_object_or_404(Arrears, id=arrears_id)
    service_order = arrears.service_order

    # Build a structure with all relevant info
    # For simplicity, we’ll gather:
    # - order_number
    # - workers
    # - vehicle
    # - services list
    # - date
    # - final_amount
    # etc.

    order_data = {
        'order_number': service_order.service_order_number,
        'date': service_order.date.strftime('%Y-%m-%d %H:%M'),
        'customer': service_order.customer.user.get_full_name(),
        'final_amount': service_order.final_amount,
        'status': service_order.status,
        'payment_method': service_order.payment_method or 'N/A',
        'vehicle': None,
        'workers': [],
        'services': [],
    }

    # Vehicle
    if service_order.vehicle:
        vehicle_obj = service_order.vehicle
        order_data['vehicle'] = {
            'car_plate': vehicle_obj.car_plate,
            'car_make': vehicle_obj.car_make,
            'car_color': vehicle_obj.car_color,
        }

    # Workers
    for w in service_order.workers.all():
        order_data['workers'].append(w.user.get_full_name())

    # Services
    for sr in service_order.rendered.all():
        order_data['services'].append({
            'service_type': sr.service.service_type,
            'price': sr.service.price,
        })

    return JsonResponse({'success': True, 'data': order_data})


@login_required(login_url='login')
def send_arrears_reminder(request, arrears_id):
    """
    Sends an email or SMS reminder to the customer about their arrears.
    """
    arrears = get_object_or_404(Arrears, id=arrears_id)
    service_order = arrears.service_order
    customer = service_order.customer

    # Check if the user can send a reminder for this arrears
    # e.g. if user is staff or belongs to the same branch
    if not request.user.is_staff and not request.user.is_superuser:
        # Worker must belong to same branch
        worker = get_object_or_404(Worker, user=request.user)
        if worker.branch != arrears.branch:
            messages.error(request, "You cannot send reminders for another branch.")
            return redirect('arrears_list')

    # Implement your email or SMS logic here:
    customer_email = customer.user.email
    phone_number = customer.user.phone_number
    # For example, sending email:
    if customer_email:
        # Your email-sending function
        subject = f"Reminder: Outstanding Arrears (Order #{service_order.service_order_number})"
        body = (
            f"Dear {customer.user.get_full_name()},\n\n"
            f"You have an outstanding arrears of GHS {arrears.amount_owed} "
            f"for Service Order #{service_order.service_order_number}. "
            f"Kindly settle this as soon as possible.\n\n"
            f"Thank you!"
        )
        # Actually send it (pseudo-code):
        # send_email(to=customer_email, subject=subject, body=body)

    # Or send SMS if you have an SMS gateway
    message = f"Dear {customer.user.get_full_name()},\n\n" \
              f"You have an outstanding arrears of GHS {arrears.amount_owed} " \
              f"for Service Order #{service_order.service_order_number}. " \
              f"Kindly settle this as soon as possible.\n\n" \
              f"Thank you!"
    send_sms(phone_number, message)

    messages.success(request, "Reminder has been sent to the customer.")
    return redirect('arrears_list')


DAY_CHOICES = [7, 15, 30]


@login_required(login_url='login')
def worker_commissions(request):
    """
    Worker view: daily commission + bonus / deduction + earnings
    for the last N days, with a trend chart.
    """
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, "You are not authorized to view commissions.")
        return redirect('index')

    # 1) range selector
    try:
        days = max(1, int(request.GET.get('days', '7')))
    except ValueError:
        days = 7

    today = date.today()
    start_date = today - timedelta(days=days - 1)

    # 2) commissions in range (single query)
    comm_qs = (Commission.objects
               .filter(worker=worker, date__range=[start_date, today])
               .values('date')
               .annotate(total_commission=Sum('amount'))
               .order_by())

    comm_map = {row['date']: row['total_commission'] for row in comm_qs}

    # 3) adjustments in range (single query)
    adj_qs = WorkerDailyAdjustment.objects.filter(
        worker=worker, date__range=[start_date, today]
    )
    adj_map = {adj.date: adj for adj in adj_qs}

    # 4) build rows / chart
    daily_rows = []
    chart_labels = []
    chart_values = []

    for i in range(days):
        d = start_date + timedelta(days=i)
        com = float(comm_map.get(d, 0))
        adj = adj_map.get(d)

        bonus = adj.bonus if adj else 0.0
        deduction = adj.deduction if adj else 0.0
        earnings = com - deduction + bonus

        daily_rows.append({
            'date': d,
            'total_commission': com,
            'bonus': bonus,
            'deduction': deduction,
            'total_earnings': earnings,
        })

        chart_labels.append(d.strftime('%Y-%m-%d'))
        chart_values.append(earnings)  # chart earnings trend

    daily_rows.reverse()  # newest first in table

    return render(request, 'layouts/workers/my_commissions.html', {
        'worker': worker,
        'days': days,
        'daily_rows': daily_rows,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_values_json': json.dumps(chart_values),
        'day_choices': DAY_CHOICES,  # ← new
    })


@login_required(login_url='login')
def create_customer(request):
    """
    AJAX endpoint to create a new Customer (and associated CustomUser).
    Returns JSON with { success: bool, customer: {id, name}, error: str }
    """
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        phone_number = request.POST.get('phone_number')
        if first_name and last_name and phone_number:
            if CustomUser.objects.filter(phone_number=phone_number).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Customer with this phone number already exists.'
                })
            new_user = CustomUser.objects.create(
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                username=phone_number,
                role='customer',
            )
            Customer.objects.create(user=new_user)
            return JsonResponse({
                'success': True,
                'customer': {
                    'id': new_user.id,
                    'name': f"{new_user.first_name} {new_user.last_name}"
                }
            })
        return JsonResponse({'success': False, 'error': 'Missing required fields.'})
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required(login_url='login')
def create_vehicle(request):
    """
    AJAX endpoint to create a new vehicle for a given customer.
    """
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        if not all([customer_id, vehicle_group_id, car_make, car_plate, car_color]):
            return JsonResponse({'success': False, 'error': 'All fields are required.'})

        customer = get_object_or_404(Customer, id=customer_id)
        vehicle_group = get_object_or_404(VehicleGroup, id=vehicle_group_id)

        vehicle = CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=vehicle_group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color,
        )
        return JsonResponse({
            'success': True,
            'vehicle': {
                'id': vehicle.id,
                'display': f"{vehicle.car_make} {vehicle.car_plate} ({vehicle.car_color})"
            }
        })
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required(login_url='login')
def get_customer_vehicles(request, customer_id):
    """
    AJAX endpoint to fetch a given customer's vehicles as JSON.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    vehicles = CustomerVehicle.objects.filter(customer=customer)
    vehicle_list = []
    for v in vehicles:
        display_str = f"{v.car_make} {v.car_plate} ({v.car_color})"
        vehicle_list.append({
            'id': v.id,
            'display': display_str
        })
    return JsonResponse({'vehicles': vehicle_list})


@login_required(login_url='login')
def get_vehicle_services(request, vehicle_id):
    """
    AJAX endpoint to fetch active services for the vehicle's group.
    """
    vehicle = get_object_or_404(CustomerVehicle, id=vehicle_id)
    vehicle_group = vehicle.vehicle_group
    services = Service.objects.filter(
        vehicle_group=vehicle_group,
        active=True
    )
    service_list = [{'id': s.id, 'name': s.service_type} for s in services]
    return JsonResponse({'services': service_list})


@staff_member_required
def enroll_worker(request):
    """
    Allows an admin to create a new Worker user (CustomUser with role='worker'),
    assign them to a branch, capture all personal, educational, employment,
    reference, and guarantor info, upload ID photos, and email/SMS them
    a password reset link to set their password.
    """
    if request.method == 'POST':
        form = EnrollWorkerForm(request.POST, request.FILES)
        if form.is_valid():
            # Check phone uniqueness before doing any DB writes
            phone_number = form.cleaned_data['phone_number']
            if CustomUser.objects.filter(phone_number=phone_number).exists():
                form.add_error('phone_number', 'This phone number is already in use.')
                return render(request, 'layouts/admin/enroll_worker.html', {'form': form})

            with transaction.atomic():
                # --- CREATE USER ---
                first_name = form.cleaned_data['first_name']
                last_name = form.cleaned_data['last_name']
                email = form.cleaned_data.get('email', '')
                user = CustomUser.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone_number=phone_number,
                    username=phone_number,
                    role='worker',
                    is_active=True,
                )

                # --- EXTRACT WORKER FIELDS ---
                branch = form.cleaned_data['branch']
                position_job = form.cleaned_data.get('position_job')
                salary = form.cleaned_data.get('salary') or 0.0
                gh_card_number = form.cleaned_data.get('gh_card_number')
                year_of_admission = form.cleaned_data.get('year_of_admission')
                is_branch_admin = form.cleaned_data.get('is_branch_admin', False)

                # personal & ID
                date_of_birth = form.cleaned_data.get('date_of_birth')
                place_of_birth = form.cleaned_data.get('place_of_birth')
                nationality = form.cleaned_data.get('nationality')
                home_address = form.cleaned_data.get('home_address')
                landmark = form.cleaned_data.get('landmark')
                ecowas_id_card_no = form.cleaned_data.get('ecowas_id_card_no')
                ecowas_id_card_photo = form.cleaned_data.get('ecowas_id_card_photo')
                passport_photo = form.cleaned_data.get('passport_photo')

                # --- CREATE WORKER PROFILE ---
                worker = Worker.objects.create(
                    user=user,
                    branch=branch,
                    position=position_job,
                    salary=salary,
                    gh_card_number=gh_card_number,
                    year_of_admission=year_of_admission,
                    is_branch_admin=is_branch_admin,
                    date_of_birth=date_of_birth,
                    place_of_birth=place_of_birth,
                    nationality=nationality,
                    home_address=home_address,
                    landmark=landmark,
                    ecowas_id_card_no=ecowas_id_card_no,
                    ecowas_id_card_photo=ecowas_id_card_photo,
                    passport_photo=passport_photo,
                )

                # --- EDUCATION RECORD ---
                WorkerEducation.objects.create(
                    worker=worker,
                    school_name=form.cleaned_data.get('school_name'),
                    school_location=form.cleaned_data.get('school_location'),
                    year_completed=form.cleaned_data.get('year_completed'),
                )

                # --- EMPLOYMENT RECORD ---
                WorkerEmployment.objects.create(
                    worker=worker,
                    employer_name=form.cleaned_data.get('employer_name'),
                    contact_number=form.cleaned_data.get('contact_number'),
                    location=form.cleaned_data.get('location'),
                    position=form.cleaned_data.get('position'),
                    last_date_of_work=form.cleaned_data.get('last_date_of_work'),
                    home_office_address=form.cleaned_data.get('home_office_address'),
                    reason_for_leaving=form.cleaned_data.get('reason_for_leaving'),
                    may_we_contact=form.cleaned_data.get('may_we_contact'),
                )

                # --- REFERENCE RECORD ---
                WorkerReference.objects.create(
                    worker=worker,
                    full_name=form.cleaned_data.get('ref_full_name'),
                    mobile_number=form.cleaned_data.get('ref_mobile_number'),
                    home_office_address=form.cleaned_data.get('ref_address'),
                )

                # --- GUARANTOR RECORD ---
                WorkerGuarantor.objects.create(
                    worker=worker,
                    full_name=form.cleaned_data.get('gua_full_name'),
                    mobile_number=form.cleaned_data.get('gua_mobile_number'),
                    home_office_address=form.cleaned_data.get('gua_address'),
                )

                # --- GENERATE PASSWORD RESET LINK ---
                current_site = get_current_site(request)
                domain = current_site.domain
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = reverse('password_reset_confirm', kwargs={
                    'uidb64': uid,
                    'token': token,
                })
                reset_link = f"https://{domain}{reset_url}"

                subject = "Welcome to AutoDash - Set Your Password"
                message = (
                    f"Hello {first_name},\n\n"
                    f"You have been enrolled as a worker at {branch.name}.\n"
                    f"Please set your password using the link below:\n\n"
                    f"{reset_link}\n\n"
                    f"Thank you!"
                )

            # send SMS (if phone provided)
            if phone_number:
                try:
                    send_sms(phone_number, message)
                except Exception as e:
                    # log or print as needed
                    print("SMS failed:", e)

            # optionally: send email
            # send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

            messages.success(
                request,
                "Worker enrolled successfully. Password reset link sent (if phone number provided)."
            )
            return redirect('enroll_worker')

        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = EnrollWorkerForm()

    return render(request, 'layouts/admin/enroll_worker.html', {'form': form})


def generate_chart(fig):
    """
    Converts a Plotly figure to a base64-encoded PNG.
    """
    img_bytes = fig.to_image(format="png")
    return base64.b64encode(img_bytes).decode('utf-8')


# @staff_member_required
@transaction.atomic
def create_customer_page(request):
    """
    Standalone page to create a new Customer (and associated CustomUser),
    plus attach an initial Vehicle in the same form.
    """
    if request.method == 'POST':
        form = CreateCustomerForm(request.POST)
        if form.is_valid():
            # 1. Extract customer fields
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            phone_number = form.cleaned_data['phone_number']
            email = form.cleaned_data['email']
            branch = form.cleaned_data['branch']
            customer_group = form.cleaned_data['customer_group']

            # 2. Extract vehicle fields
            vehicle_group = form.cleaned_data['vehicle_group']
            car_make = form.cleaned_data['car_make']
            car_plate = form.cleaned_data['car_plate']
            car_color = form.cleaned_data['car_color']

            # Check for phone conflict
            if CustomUser.objects.filter(phone_number=phone_number).exists():
                messages.error(request, "This phone number is already used by another user.")
                return render(request, 'layouts/create_customer.html', {'form': form})

            # 3. Create the CustomUser
            user = CustomUser.objects.create(
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                username=phone_number,  # or a custom username logic
                email=email,
                role='customer'
            )

            # 4. Create the Customer
            customer = Customer.objects.create(user=user, branch=branch, customer_group=customer_group)

            # 5. Create the initial Vehicle
            CustomerVehicle.objects.create(
                customer=customer,
                vehicle_group=vehicle_group,
                car_plate=car_plate,
                car_make=car_make,
                car_color=car_color,
            )

            # 6. Send SMS
            try:
                sms_text = (
                    f"Hello {first_name}, you have been registered as a Customer at Autodash. "
                    f"Your phone: {phone_number}. Welcome aboard!"
                )
                # send_sms(phone_number, sms_text)
                messages.success(request, f"Customer + Vehicle created, SMS sent to {phone_number}.")
            except Exception as e:
                messages.warning(request, f"Customer + Vehicle created, but SMS not sent: {str(e)}")

            # 7. Redirect or show success
            return redirect('create_customer_page')  # or maybe to a "manage_customers" view
        else:
            messages.error(request, "Please correct the errors below.")
            return render(request, 'layouts/create_customer.html', {'form': form})
    else:
        form = CreateCustomerForm()
    return render(request, 'layouts/create_customer.html', {'form': form})


# @staff_member_required
@transaction.atomic
def create_vehicle_page(request):
    """
    Standalone page to create a new Vehicle and assign it to a Customer.
    After success, sends an SMS about the new vehicle.
    """
    if request.method == 'POST':
        form = CreateVehicleForm(request.POST)
        if form.is_valid():
            customer = form.cleaned_data['customer']
            vehicle_group = form.cleaned_data['vehicle_group']
            car_make = form.cleaned_data['car_make']
            car_plate = form.cleaned_data['car_plate']
            car_color = form.cleaned_data['car_color']

            # Create CustomerVehicle
            vehicle = CustomerVehicle.objects.create(
                customer=customer,
                vehicle_group=vehicle_group,
                car_make=car_make,
                car_plate=car_plate,
                car_color=car_color
            )

            # Send SMS to the customer's phone
            try:
                phone_number = customer.user.phone_number
            except Exception as e:
                print(e)
                messages.info(request, "Vehicle created.")
                return redirect('create_vehicle_page')
            if phone_number:
                try:
                    sms_text = (
                        f"Hello {customer.user.first_name}, "
                        f"a new vehicle: {car_make} - {car_plate} has been assigned to your account."
                    )
                    send_sms(phone_number, sms_text)
                    messages.success(request, f"Vehicle created, and SMS sent to {phone_number}.")
                except Exception as e:
                    messages.warning(request, f"Vehicle created, but SMS not sent: {str(e)}")
            else:
                messages.info(request, "Vehicle created. No phone number available for SMS.")

            return redirect('create_vehicle_page')  # or wherever
        else:
            messages.error(request, "Please correct the errors below.")
            return render(request, 'layouts/create_vehicle.html', {'form': form})
    else:
        form = CreateVehicleForm()
    return render(request, 'layouts/create_vehicle.html', {'form': form})


from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Max, Q
from datetime import datetime, timedelta
from .forms import ReportForm
from .models import (
    Branch, Worker, Customer, ServiceRenderedOrder, ServiceRendered,
    CustomerVehicle, Arrears, Revenue, Expense, Commission, Product, ProductPurchased
)


@staff_member_required
def generate_report(request):
    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            report_type = form.cleaned_data['report_type']
            view_type = form.cleaned_data['view_type']

            branch_filter = form.cleaned_data['branch']
            worker_filter = form.cleaned_data['worker']
            customer_filter = form.cleaned_data['customer']

            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data['end_date']
            month = form.cleaned_data['month']
            year = form.cleaned_data['year']

            # Derive the final start/end date range
            today = timezone.now().date()
            if view_type == 'month_year' and month and year:
                # Range covering that month
                first_day = datetime(year, month, 1).date()
                if month == 12:
                    last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
                else:
                    last_day = datetime(year, month + 1, 1).date() - timedelta(days=1)
                final_start = first_day
                final_end = last_day
            else:
                # date_range
                if not start_date:
                    start_date = today.replace(day=1)  # fallback
                if not end_date:
                    end_date = today
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                final_start = start_date
                final_end = end_date

            # Prepare context
            context = {
                'report_type': report_type,
                'view_type': view_type,
                'final_start': final_start,
                'final_end': final_end,
                'branch_filter': branch_filter,
                'worker_filter': worker_filter,
                'customer_filter': customer_filter,
                'results': {},  # We'll store the query results in 'results'
            }

            # ===============  A) Branch Report  ===============
            if report_type == 'branch':
                # Either a specific branch or all branches
                branches_qs = Branch.objects.all()
                if branch_filter:
                    branches_qs = branches_qs.filter(id=branch_filter.id)

                branch_data = []
                for br in branches_qs:
                    # Revenue in range
                    rev_total = Revenue.objects.filter(
                        branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('final_amount'))['total'] or 0

                    # Expense in range
                    exp_total = Expense.objects.filter(
                        branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    # Commission in range
                    comm_total = Commission.objects.filter(
                        worker__branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    # Calculate Gross Sales (Revenue - Commission) and Profit (Gross Sales - Expense)
                    gross_sales = rev_total - comm_total
                    profit = gross_sales - exp_total

                    # Workers & customers
                    worker_count = Worker.objects.filter(branch=br).count()
                    customer_count = Customer.objects.filter(branch=br).count()

                    branch_data.append({
                        'branch': br,
                        'revenue': rev_total,
                        'commission': comm_total,
                        'gross_sales': gross_sales,
                        'profit': profit,
                        'expense': exp_total,
                        'workers': worker_count,
                        'customers': customer_count,
                    })

                context['results']['branch_data'] = branch_data

                branch_totals = {
                    'revenue': sum(row['revenue'] for row in branch_data),
                    'commission': sum(row['commission'] for row in branch_data),
                    'gross_sales': sum(row['gross_sales'] for row in branch_data),
                    'expense': sum(row['expense'] for row in branch_data),
                    'profit': sum(row['profit'] for row in branch_data),
                    'workers': sum(row['workers'] for row in branch_data),
                    'customers': sum(row['customers'] for row in branch_data),
                }
                context['results']['branch_totals'] = branch_totals

            # ===============  B) Worker Report  ===============
            elif report_type == 'worker':
                # If a specific worker is chosen, or all workers
                workers_qs = Worker.objects.all()
                if worker_filter:
                    workers_qs = workers_qs.filter(id=worker_filter.id)
                if branch_filter:
                    workers_qs = workers_qs.filter(branch=branch_filter)

                # For each worker, gather stats
                worker_data = []
                for wk in workers_qs:
                    # Services completed in range
                    completed_orders = ServiceRenderedOrder.objects.filter(
                        workers=wk,
                        status='completed',
                        date__range=[final_start, final_end]
                    ).distinct()
                    total_services = completed_orders.count()

                    # Commission
                    comm_total = Commission.objects.filter(
                        worker=wk,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    # Ratings
                    # If your rating is stored in ServiceRenderedOrder.customer_rating
                    # for orders involving this worker
                    ratings = completed_orders.exclude(customer_rating__isnull=True).values_list('customer_rating',
                                                                                                 flat=True)
                    if ratings:
                        avg_rating = sum(ratings) / len(ratings)
                    else:
                        avg_rating = 0

                    worker_data.append({
                        'worker': wk,
                        'total_services': total_services,
                        'total_commission': comm_total,
                        'avg_rating': round(avg_rating, 2),
                    })

                context['results']['worker_data'] = worker_data

            # ===============  C) Customer Report  ===============
            elif report_type == 'customer':
                # If specific customer or all
                cust_qs = Customer.objects.all()
                if customer_filter:
                    cust_qs = cust_qs.filter(id=customer_filter.id)
                if branch_filter:
                    cust_qs = cust_qs.filter(branch=branch_filter)  # if you store branch in Customer

                customer_data = []
                for cst in cust_qs:
                    # Orders in range
                    orders = ServiceRenderedOrder.objects.filter(
                        customer=cst,
                        date__range=[final_start, final_end]
                    )
                    total_orders = orders.count()
                    total_spend = orders.aggregate(total=Sum('final_amount'))['total'] or 0

                    # On-credit usage
                    on_credit_orders = orders.filter(status='onCredit').count()
                    # Or arrears usage
                    total_arrears_amount = Arrears.objects.filter(
                        service_order__customer=cst,
                        date_created__date__range=[final_start, final_end]
                    ).aggregate(Sum('amount_owed'))['amount_owed__sum'] or 0

                    customer_data.append({
                        'customer': cst,
                        'orders': total_orders,
                        'total_spend': total_spend,
                        'on_credit_count': on_credit_orders,
                        'arrears_amount': total_arrears_amount,
                    })

                context['results']['customer_data'] = customer_data

            # ===============  D) Services Report  ===============
            elif report_type == 'services':
                # We want to find which services occur frequently, total revenue from each, etc.

                # In the range:
                # We look at ServiceRendered -> .service + .order to see how many times each service was done
                sr_qs = ServiceRendered.objects.filter(order__date__range=[final_start, final_end])
                if branch_filter:
                    sr_qs = sr_qs.filter(order__branch=branch_filter)

                # Group by service
                service_stats = sr_qs.values('service__service_type').annotate(
                    times_rendered=Count('id'),
                    total_revenue=Sum('order__final_amount')  # approximate, if you want a finer approach
                ).order_by('-times_rendered')

                context['results']['service_stats'] = service_stats

            # ===============  E) Products Report  ===============
            elif report_type == 'products':
                # We want to see which products were sold the most, total sales, top buyers, etc.
                product_sales_qs = ProductPurchased.objects.filter(service_order__date__range=[final_start, final_end])
                # Or if you have standalone product sale model (ProductSale), combine them if you like.

                if branch_filter:
                    product_sales_qs = product_sales_qs.filter(service_order__branch=branch_filter)

                # Group by product
                product_stats = product_sales_qs.values('product__name').annotate(
                    total_quantity=Sum('quantity'),
                    total_sales=Sum('total_price')
                ).order_by('-total_quantity')

                context['results']['product_stats'] = product_stats

            # ===============  F) Financial Report  ===============
            elif report_type == 'financial':
                # Summaries of revenue, expenses, commissions, on-credit, net profit, etc.
                rev_qs = Revenue.objects.filter(date__range=[final_start, final_end])
                exp_qs = Expense.objects.filter(date__range=[final_start, final_end])
                comm_qs = Commission.objects.filter(date__range=[final_start, final_end])
                arr_qs = Arrears.objects.filter(date_created__date__range=[final_start, final_end])

                if branch_filter:
                    rev_qs = rev_qs.filter(branch=branch_filter)
                    exp_qs = exp_qs.filter(branch=branch_filter)
                    comm_qs = comm_qs.filter(worker__branch=branch_filter)
                    arr_qs = arr_qs.filter(branch=branch_filter)

                total_rev = rev_qs.aggregate(Sum('final_amount'))['final_amount__sum'] or 0
                total_exp = exp_qs.aggregate(Sum('amount'))['amount__sum'] or 0
                total_comm = comm_qs.aggregate(Sum('amount'))['amount__sum'] or 0
                total_arrears = arr_qs.aggregate(Sum('amount_owed'))['amount_owed__sum'] or 0
                net_profit = total_rev - total_exp

                context['results']['financial'] = {
                    'total_revenue': total_rev,
                    'total_expenses': total_exp,
                    'total_commission': total_comm,
                    'total_arrears': total_arrears,
                    'net_profit': net_profit,
                    'revenue_list': rev_qs,
                    'expense_list': exp_qs,
                    'commission_list': comm_qs,
                    'arrears_list': arr_qs,
                }

            return render(request, 'layouts/reports/report_display.html', context)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ReportForm()

    return render(request, 'layouts/reports/select_report.html', {'form': form})


######### Customer Page Views
def customer_page_add_vehicle_to_customer(request, customer_id):
    """
    POST endpoint to add a new vehicle for a specific Customer.
    Expects form data: vehicle_group, car_make, car_plate, car_color
    Returns JSON: { success: true, vehicle: {...} } on success
    """
    if request.method == 'POST':
        customer = get_object_or_404(Customer, pk=customer_id)

        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        # Basic validation
        if not all([vehicle_group_id, car_make, car_plate, car_color]):
            return JsonResponse({'success': False, 'error': 'Missing fields'}, status=400)

        try:
            group = VehicleGroup.objects.get(pk=vehicle_group_id)
        except VehicleGroup.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid vehicle group'}, status=400)

        new_vehicle = CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color
        )

        return JsonResponse({
            'success': True,
            'vehicle': {
                'id': new_vehicle.id,
                'car_make': new_vehicle.car_make,
                'car_plate': new_vehicle.car_plate,
                'car_color': new_vehicle.car_color,
                'vehicle_group': new_vehicle.vehicle_group.group_name
            }
        })
    # If not POST, return method not allowed
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


def customer_page_remove_vehicle_from_customer(request, customer_id):
    """
    POST endpoint to remove a vehicle from a Customer.
    Expects JSON body: { "vehicle_id": <int> }
    Returns { success: true } on success
    """
    if request.method == 'POST':
        customer = get_object_or_404(Customer, pk=customer_id)

        import json
        try:
            data = json.loads(request.body)
            vehicle_id = data.get('vehicle_id')
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

        if not vehicle_id:
            return JsonResponse({'success': False, 'error': 'No vehicle_id provided'}, status=400)

        try:
            vehicle = CustomerVehicle.objects.get(pk=vehicle_id, customer=customer)
        except CustomerVehicle.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Vehicle not found for this customer'
            }, status=404)

        vehicle.delete()
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


def customer_page_add_subscription_to_customer(request, customer_id):
    """
    POST endpoint to add a Subscription to a Customer.
    Expects form data: subscription_id
    Returns JSON: { success: true, subscription: {...}, start_date, end_date } on success
    """
    if request.method == 'POST':
        customer = get_object_or_404(Customer, pk=customer_id)
        subscription_id = request.POST.get('subscription_id')

        if not subscription_id:
            return JsonResponse({'success': False, 'error': 'No subscription chosen'}, status=400)

        try:
            subscription_obj = Subscription.objects.get(pk=subscription_id)
        except Subscription.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Subscription not found'}, status=404)

        start_date = timezone.now().date()
        end_date = start_date + timezone.timedelta(days=subscription_obj.duration_in_days)

        cs = CustomerSubscription.objects.create(
            customer=customer,
            subscription=subscription_obj,
            start_date=start_date,
            end_date=end_date
        )

        return JsonResponse({
            'success': True,
            'subscription': {
                'id': cs.id,
                'name': subscription_obj.name,
            },
            'start_date': cs.start_date.strftime('%Y-%m-%d'),
            'end_date': cs.end_date.strftime('%Y-%m-%d'),
        })
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


def vehicle_list(request):
    vehicles = CustomerVehicle.objects.all().select_related('customer__user', 'vehicle_group')
    context = {
        'vehicles': vehicles,
    }
    return render(request, 'layouts/all_vehicles.html', context)


def edit_vehicle(request, pk):
    vehicle = get_object_or_404(CustomerVehicle, pk=pk)
    if request.method == 'POST':
        form = EditCustomerVehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer Vehicle Edited Successfully")
            return redirect('vehicle_list')  # update with your URL name if different
    else:
        form = EditCustomerVehicleForm(instance=vehicle)
    context = {
        'form': form,
        'vehicle': vehicle,
    }
    return render(request, 'layouts/vehicle_edit.html', context)


def edit_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer updated successfully.")
            return redirect('manage_customers')  # Change this to your manage customers URL name
    else:
        form = CustomerEditForm(instance=customer)
    return render(request, 'layouts/edit_customer.html', {'form': form, 'customer': customer})


@staff_member_required
@transaction.atomic
def enroll_subscription(request, customer_id):
    """
    Enrolls a customer in a new subscription.
    GET: Display a form with a dropdown of available subscriptions.
         When a subscription is selected, its services are shown via JS.
    POST: Create a new CustomerSubscription for the customer.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    subscriptions = Subscription.objects.all()

    # Build a dictionary mapping subscription id to its services (id, service_type, price)
    sub_services = {}
    for sub in subscriptions:
        sub_services[sub.id] = list(sub.services.all().values('id', 'service_type', 'price'))

    # Convert the dictionary to a JSON string.
    sub_services_json = json.dumps(sub_services)

    if request.method == 'POST':
        sub_id = request.POST.get('subscription')
        if not sub_id:
            error = "Please select a subscription."
            context = {
                'customer': customer,
                'subscriptions': subscriptions,
                'sub_services_json': sub_services_json,
                'error': error,
            }
            return render(request, 'layouts/admin/enroll_subscription.html', context)
        try:
            subscription = Subscription.objects.get(id=sub_id)
        except Subscription.DoesNotExist:
            error = "Invalid subscription selected."
            context = {
                'customer': customer,
                'subscriptions': subscriptions,
                'sub_services_json': sub_services_json,
                'error': error,
            }
            return render(request, 'layouts/admin/enroll_subscription.html', context)
        # Create a new CustomerSubscription
        start_date = timezone.now().date()
        end_date = start_date + timezone.timedelta(days=subscription.duration_in_days)
        assert_unique_active_subscription(customer, subscription)
        CustomerSubscription.objects.create(
            customer=customer,
            subscription=subscription,
            start_date=start_date,
            end_date=end_date,
            branch=customer.branch,
            used_amount=0,
            sub_amount_remaining=subscription.amount
        )
        return redirect('customer_detail_admin', customer_id=customer.id)

    return render(request, 'layouts/admin/enroll_subscription.html', {
        'customer': customer,
        'subscriptions': subscriptions,
        'sub_services_json': sub_services_json,
    })


@staff_member_required
@transaction.atomic
def renew_subscription(request, customer_id):
    """
    Renews the customer's latest subscription.

    GET: Display the latest subscription details with a "Renew" button.
    POST: Reset used_amount to 0, add the subscription's amount to the remaining balance,
          and create a renewal trail record.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    # Get the latest subscription; adjust ordering as needed.
    latest_sub = CustomerSubscription.objects.filter(customer=customer).order_by('-start_date').first()
    if not latest_sub:
        from django.contrib import messages
        messages.error(request, "Customer has no subscription to renew.")
        return redirect('customer_detail_admin', customer_id=customer.id)

    if request.method == 'POST':
        renewal_amount = latest_sub.subscription.amount
        # Reset used amount and add the new amount to the remaining balance.
        latest_sub.used_amount = 0
        latest_sub.sub_amount_remaining += renewal_amount
        latest_sub.last_rollover = timezone.now()
        latest_sub.save()

        # Create a renewal trail record.
        CustomerSubscriptionRenewalTrail.objects.create(
            subscription=latest_sub,
            amount_for_renewal=renewal_amount,
            customer=customer
        )

        from django.contrib import messages
        messages.success(request, "Subscription renewed successfully!")
        return redirect('customer_detail_admin', customer_id=customer.id)

    return render(request, 'layouts/admin/renew_subscription.html', {
        'customer': customer,
        'subscription': latest_sub,
    })


@login_required(login_url='login')
@transaction.atomic
def log_service_scanned(request, customer_id):
    """
    A specialized flow for scanning a QR code that identifies a customer (customer_id).
    We skip selecting the customer because it's known from the URL.
    The worker picks the vehicle, services, workers, etc., then we create an order in 'pending' status.
    Finally, redirect to confirm_service_rendered.
    """
    user = request.user
    try:
        worker = Worker.objects.get(user=user)
    except Worker.DoesNotExist:
        messages.error(request, "You are not authorized to log services.")
        return redirect('index')

    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == 'POST':
        form = LogServiceScannedForm(branch=worker.branch, customer=customer, data=request.POST)
        if form.is_valid():
            # We don't pick a customer from the form; we already have 'customer'
            vehicle = form.cleaned_data['vehicle']
            selected_services = form.cleaned_data['service']
            selected_workers = form.cleaned_data['workers']
            # If you want product logic, handle it similarly:
            selected_products = form.cleaned_data.get('products', [])
            product_quantities = request.POST.getlist('product_quantity')  # etc.

            # Sum up services at standard (non-negotiated) price
            total_services = sum(svc.price for svc in selected_services)
            total = total_services

            # Create the ServiceRenderedOrder with status 'pending'
            new_order = ServiceRenderedOrder.objects.create(
                customer=customer,
                user=request.user,
                total_amount=total,
                final_amount=total,
                vehicle=vehicle,
                branch=worker.branch,
                status='pending'
            )
            new_order.workers.set(selected_workers)

            # Create ServiceRendered entries
            for svc in selected_services:
                sr = ServiceRendered.objects.create(
                    service=svc,
                    order=new_order,
                    negotiated_price=svc.price,  # handle negotiation at confirmation
                    payment_type="Cash"
                )
                sr.workers.set(selected_workers)

            messages.success(request, "Service logged successfully (status=pending).")
            return redirect('confirm_service_rendered', pk=new_order.pk)
        else:
            messages.error(request, "Form is invalid. Please correct any errors.")
    else:
        form = LogServiceScannedForm(branch=worker.branch, customer=customer)

    # additional context for your template
    products = Product.objects.filter(branch=worker.branch)
    context = {
        'form': form,
        'customer': customer,
        'products': products,
    }
    return render(request, 'layouts/workers/log_service_scanned.html', context)


@staff_member_required
def generate_subscription_card(request, subscription_id):
    from io import BytesIO
    from base64 import b64encode
    subscription = get_object_or_404(CustomerSubscription, id=subscription_id)
    customer = subscription.customer
    scanned_url = request.build_absolute_uri(reverse('log_service_scanned', args=[customer.id]))
    is_active = subscription.is_active()

    # Generate QR code image
    qr = QRCode(version=1, box_size=5, border=2)
    qr.add_data(scanned_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    qr_base64 = b64encode(buffer.getvalue()).decode('utf-8')

    context = {
        'subscription': subscription,
        'customer': customer,
        'is_active': is_active,
        'status_text': "Active" if is_active else "Expired",
        'qr_base64': qr_base64,
        'scanned_url': scanned_url
    }
    return render(request, 'layouts/admin/subscription_card.html', context)


def _parse_date(val, default):
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


@login_required
def daily_budget_insights(request):
    user = request.user

    # ————— Branch selection —————
    if user.is_superuser:
        branches = Branch.objects.all()
        branch_id = request.GET.get("branch", "")
        branch = (
            get_object_or_404(Branch, id=branch_id)
            if branch_id else
            (branches.first() if branches.exists() else None)
        )
        show_branch_selector = True
    else:
        branches = None
        try:
            branch = user.worker_profile.branch
            show_branch_selector = False
        except Worker.DoesNotExist:
            messages.error(request, "You must belong to a branch to view insights.")
            return redirect("index")

    if not branch:
        messages.error(request, "No branch available.")
        return redirect("index")

    # ————— Date range (default last 7 days) —————
    today = date.today()
    end_date = _parse_date(request.GET.get("end_date"), today)
    start_date = _parse_date(request.GET.get("start_date"), end_date - timedelta(days=6))
    if start_date > end_date:
        start_date, end_date = end_date - timedelta(days=6), end_date

    # ————— Build each day’s insight —————
    days = (end_date - start_date).days + 1
    labels = []
    budgets_data = []
    expenses_data = []
    insights = []

    for i in range(days):
        current = start_date + timedelta(days=i)
        labels.append(current.strftime("%Y-%m-%d"))

        # (a) Weekly budget for that weekday
        wb = WeeklyBudget.objects.filter(
            branch=branch, weekday=current.weekday()
        ).first()
        budget_amt = wb.budget_amount if wb else 0.0

        # (b) Sum all Expense rows (one-off + recurring minted by middleware)
        total_exp = (
                Expense.objects
                .filter(branch=branch, date=current)
                .aggregate(total=Sum("amount"))["total"]
                or 0.0
        )

        diff = budget_amt - total_exp
        if diff > 0:
            status = "Under"
        elif diff < 0:
            status = "Over"
        else:
            status = "On Target"

        insights.append({
            "date": current,
            "budget": budget_amt,
            "expense": total_exp,
            "difference": diff,
            "status": status
        })

        budgets_data.append(budget_amt)
        expenses_data.append(total_exp)

    # reverse so most recent shows first in table
    insights.reverse()

    return render(request, "layouts/budgets/insights.html", {
        "branches": branches,
        "show_branch_selector": show_branch_selector,
        "selected_branch_id": branch.id,
        "start_date": start_date,
        "end_date": end_date,
        "insights": insights,
        "labels_json": json.dumps(labels),
        "budgets_json": json.dumps(budgets_data),
        "expenses_json": json.dumps(expenses_data),
    })


@staff_member_required
def set_weekly_budgets(request):
    user = request.user

    # —————— Branch resolution ——————
    if user.is_superuser:
        branches = Branch.objects.all()
        # on GET come from ?branch=...
        if request.method == "GET":
            branch_id = request.GET.get("branch")
        else:
            # on POST we also expect a hidden "branch" field
            branch_id = request.POST.get("branch")
        if branch_id:
            branch = get_object_or_404(Branch, id=branch_id)
        else:
            branch = branches.first() if branches.exists() else None
    else:
        # branch‐workers only get their own
        try:
            branch = user.worker_profile.branch
        except Worker.DoesNotExist:
            messages.error(request, "You must be a branch worker to set budgets.")
            return redirect("index")
        branches = None

    if not branch:
        messages.error(request, "No branch available.")
        return redirect("index")

    # — Load existing budgets into dict {weekday: instance} —
    existing = {wb.weekday: wb for wb in WeeklyBudget.objects.filter(branch=branch)}

    if request.method == "POST":
        # Save all 7 days
        for weekday, _ in WeeklyBudget.WEEKDAY_CHOICES:
            raw = request.POST.get(f"budget_{weekday}", "").strip()
            try:
                amt = float(raw) if raw else 0.0
            except ValueError:
                amt = 0.0

            if weekday in existing:
                wb = existing[weekday]
                wb.budget_amount = amt
                wb.save()
            else:
                WeeklyBudget.objects.create(
                    branch=branch,
                    weekday=weekday,
                    budget_amount=amt
                )

        messages.success(request, f"Weekly budgets for {branch.name} updated.")
        # redirect back to GET so you can see saved values
        if user.is_superuser:
            return redirect(f"{request.path}?branch={branch.id}")
        return redirect("set_weekly_budgets")

    # — GET: prepare initial values (0.0 if missing) —
    initial = {
        wd: existing.get(wd).budget_amount if wd in existing else 0.0
        for wd, _ in WeeklyBudget.WEEKDAY_CHOICES
    }

    return render(request, "layouts/budgets/set_weekly.html", {
        "branch": branch,
        "branches": branches,
        "weekday_choices": WeeklyBudget.WEEKDAY_CHOICES,
        "initial": initial,
        "show_branch_selector": user.is_superuser,
        "selected_branch_id": str(branch.id),
    })


@staff_member_required
def sales_targets_manage(request):
    # 1) Ensure one SalesTarget per branch×{weekly,monthly}
    for b in Branch.objects.all():
        for freq in (SalesTarget.FREQUENCY_WEEKLY, SalesTarget.FREQUENCY_MONTHLY):
            SalesTarget.objects.get_or_create(
                branch=b,
                frequency=freq,
                defaults={'target_amount': 0.0}
            )
        # and one DailySalesTarget per branch×weekday
        for wd, _ in DailySalesTarget.WEEKDAY_CHOICES:
            DailySalesTarget.objects.get_or_create(
                branch=b,
                weekday=wd,
                defaults={'target_amount': 0.0}
            )

    WMFormSet = modelformset_factory(
        SalesTarget,
        fields=('branch', 'frequency', 'target_amount'),
        extra=0
    )
    DFormSet = modelformset_factory(
        DailySalesTarget,
        fields=('branch', 'weekday', 'target_amount'),
        extra=0
    )

    if request.method == 'POST':
        wm_fs = WMFormSet(request.POST, prefix='wm', queryset=SalesTarget.objects.all())
        dt_fs = DFormSet(request.POST, prefix='dt', queryset=DailySalesTarget.objects.all())

        if wm_fs.is_valid() and dt_fs.is_valid():
            wm_fs.save()
            dt_fs.save()
            messages.success(request, "All targets have been updated.")
            return redirect('sales_targets_manage')
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        wm_fs = WMFormSet(prefix='wm', queryset=SalesTarget.objects.all())
        dt_fs = DFormSet(prefix='dt', queryset=DailySalesTarget.objects.all())

    return render(request, 'layouts/admin/sales_targets_manage.html', {
        'wm_formset': wm_fs,
        'dt_formset': dt_fs,
    })


def _first_of_month(dt: date) -> date:
    return dt.replace(day=1)


def _end_of_month(dt: date) -> date:
    # move to first of next month, then back one day
    if dt.month == 12:
        nm = date(dt.year + 1, 1, 1)
    else:
        nm = date(dt.year, dt.month + 1, 1)
    return nm - timedelta(days=1)


def _shift_months(dt: date, months: int) -> date:
    """
    Shift dt by -months months, landing on the first of that month.
    """
    # compute year and month
    year = dt.year
    month = dt.month - months
    # wrap underflows
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _end_of_month(d):
    # helper to get last day of month
    from calendar import monthrange
    return d.replace(day=monthrange(d.year, d.month)[1])


def _shift_months(d, n):
    # helper: subtract n months
    month = d.month - n - 1
    year = d.year + month // 12
    month = month % 12 + 1
    return d.replace(year=year, month=month, day=1)


@staff_member_required
def sales_targets_report(request):
    # ————————————— Weekly/Monthly Section ————————————— #
    freq = request.GET.get('freq', SalesTarget.FREQUENCY_MONTHLY)
    today = date.today()

    if freq == SalesTarget.FREQUENCY_WEEKLY:
        ws = request.GET.get('week_start')
        try:
            week_start = date.fromisoformat(ws) if ws else today - timedelta(days=today.weekday())
        except ValueError:
            week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        period_label = f"{week_start:%Y-%m-%d} – {week_end:%Y-%m-%d}"
        rev_qs = Revenue.objects.filter(date__gte=week_start, date__lte=week_end)
    else:
        ym = request.GET.get('year_month', today.strftime("%Y-%m"))
        try:
            y, m = map(int, ym.split('-'))
            start = date(y, m, 1)
        except:
            start = today.replace(day=1)
        end = _end_of_month(start)
        period_label = start.strftime('%B %Y')
        rev_qs = Revenue.objects.filter(date__gte=start, date__lte=end)

    # revenue by branch
    rev_by_branch = (
        rev_qs
        .values('branch__id', 'branch__name')
        .annotate(revenue=Sum('final_amount'))
        .order_by('branch__name')
    )
    targets = {t.branch_id: t.target_amount for t in SalesTarget.objects.filter(frequency=freq)}

    rows = []
    for b in Branch.objects.order_by('name'):
        rev = next((x['revenue'] for x in rev_by_branch if x['branch__id'] == b.id), 0)
        tgt = targets.get(b.id, 0)
        rows.append({'branch': b.name, 'revenue': rev, 'target': tgt, 'met': rev >= tgt})

    # prepare hit/miss history for last 6 periods
    labels = []
    history = []
    for i in range(5, -1, -1):
        if freq == SalesTarget.FREQUENCY_WEEKLY:
            ps = week_start - timedelta(weeks=i)
            pe = ps + timedelta(days=6)
            key = ps.strftime('%Y-%m-%d')
            qs = Revenue.objects.filter(date__gte=ps, date__lte=pe)
        else:
            ms = _shift_months(start, i)
            me = _end_of_month(ms)
            key = ms.strftime('%Y-%m')
            qs = Revenue.objects.filter(date__gte=ms, date__lte=me)
        labels.append(key)
        by_br = {r['branch__id']: r['total'] for r in qs.values('branch__id').annotate(total=Sum('final_amount'))}
        hits = []
        for b in Branch.objects.order_by('name'):
            amt = by_br.get(b.id, 0)
            hit = amt >= targets.get(b.id, 0)
            hits.append(hit)
        history.append(hits)

    chart_data = [
        {'label': b.name, 'data': [1 if history[p][i] else 0 for p in range(len(history))]}
        for i, b in enumerate(Branch.objects.order_by('name'))
    ]

    # ————————————— Daily Insights Section ————————————— #
    # branch dropdown for daily only
    branch_qs = Branch.objects.order_by('name')
    daily_branch_id = request.GET.get('daily_branch', '')
    if daily_branch_id:
        daily_branch = get_object_or_404(Branch, id=daily_branch_id)
    else:
        daily_branch = branch_qs.first()  # default
    # date range for daily
    ds = request.GET.get('daily_start', '')
    de = request.GET.get('daily_end', '')
    try:
        daily_start = date.fromisoformat(ds) if ds else today - timedelta(days=6)
    except:
        daily_start = today - timedelta(days=6)
    try:
        daily_end = date.fromisoformat(de) if de else today
    except:
        daily_end = today
    if daily_start > daily_end:
        daily_start, daily_end = daily_end, daily_start

    days_count = (daily_end - daily_start).days + 1
    daily_dates = [daily_start + timedelta(days=i) for i in range(days_count)]
    daily_labels = [d.strftime('%Y-%m-%d') for d in daily_dates]

    # build series for single branch
    rev_series = []
    tgt_series = []
    daily_table = []
    for d in daily_dates:
        rev = (Revenue.objects
               .filter(branch=daily_branch, date=d)
               .aggregate(total=Sum('final_amount'))['total'] or 0)
        dst = DailySalesTarget.objects.filter(branch=daily_branch, weekday=d.weekday()).first()
        tgt = dst.target_amount if dst else 0
        rev_series.append(float(rev))
        tgt_series.append(float(tgt))
        daily_table.append({
            'date': d.strftime('%Y-%m-%d'),
            'branch': daily_branch.name,
            'revenue': rev,
            'target': tgt,
            'met': rev >= tgt,
        })

    rev_series.reverse()
    tgt_series.reverse()
    daily_table.reverse()
    daily_labels.reverse()

    daily_chart = [{
        'branch': daily_branch.name,
        'revenue': rev_series,
        'target': tgt_series,
    }]

    return render(request, 'layouts/admin/sales_targets_report.html', {
        # weekly/monthly
        'freq': freq,
        'period_label': period_label,
        'rows': rows,
        'labels': json.dumps(labels),
        'chart_data': json.dumps(chart_data),
        # daily
        'branch_list': branch_qs,
        'selected_daily_branch': str(daily_branch.id),
        'daily_start_str': daily_start.isoformat(),
        'daily_end_str': daily_end.isoformat(),
        'daily_labels': json.dumps(daily_labels),
        'daily_chart': json.dumps(daily_chart),
        'daily_table': daily_table,
    })


# Period options
PERIOD_CHOICES = [
    ('1_week', '1 Week'),
    ('2_weeks', '2 Weeks'),
    ('3_weeks', '3 Weeks'),
    ('1_month', '1 Month'),
    ('3_months', '3 Months'),
    ('6_months', '6 Months'),
    ('1_year', '1 Year'),
    ('2_years', '2 Years'),
]
PERIOD_DELTAS = {
    '1_week': timedelta(weeks=1),
    '2_weeks': timedelta(weeks=2),
    '3_weeks': timedelta(weeks=3),
    '1_month': timedelta(days=30),
    '3_months': timedelta(days=90),
    '6_months': timedelta(days=182),
    '1_year': timedelta(days=365),
    '2_years': timedelta(days=365 * 2),
}


@staff_or_branch_admin_required
def dormant_vehicles(request):
    user = request.user
    today = timezone.now().date()

    # — Branch selection for superusers —
    if user.is_superuser:
        branches = Branch.objects.all()
        branch_id = request.GET.get('branch', '')
        branch = Branch.objects.filter(id=branch_id).first() if branch_id else None
        show_branch_selector = True
    else:
        branches = None
        # branch-admin or staff: fixed to their branch
        branch = user.worker_profile.branch
        show_branch_selector = False

    # — Period selection & cutoff calculation —
    period_key = request.GET.get('period', '3_months')
    delta = PERIOD_DELTAS.get(period_key, PERIOD_DELTAS['3_months'])
    cutoff = today - delta

    # — Build queryset of vehicles with latest service date ≤ cutoff or never serviced —
    qs = CustomerVehicle.objects.annotate(
        last_service=Max('servicerenderedorder__date'),
        other_vehicles=Count('customer__vehicles') - 1
    )
    # filter by branch if set
    if branch:
        qs = qs.filter(customer__branch=branch)
    # dormant: last_service is null (never) OR ≤ cutoff
    qs = qs.filter(Q(last_service__lte=cutoff) | Q(last_service__isnull=True))
    qs = qs.select_related('customer__user')

    # — Handle deletion actions —
    if request.method == 'POST':
        action = request.POST.get('action')
        vehicle_id = request.POST.get('vehicle_id')
        vehicle = get_object_or_404(CustomerVehicle, id=vehicle_id)
        if action == 'delete_vehicle':
            vehicle.delete()
            messages.success(request, f"Vehicle {vehicle.car_plate} deleted.")
        elif action == 'delete_customer':
            cust = vehicle.customer
            vehicle.delete()
            cust.delete()
            messages.success(request, f"Vehicle and customer {cust.user.get_full_name()} deleted.")
        return redirect('dormant_vehicles')

    return render(request, 'layouts/admin/dormant_vehicles.html', {
        'branches': branches,
        'show_branch_selector': show_branch_selector,
        'selected_branch': branch.id if branch else '',
        'period_choices': PERIOD_CHOICES,
        'selected_period': period_key,
        'cutoff': cutoff,
        'vehicles': qs,
    })


# All in one-link views

from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

SIGNER_SALT = 'customer-history-link'
LINK_EXPIRY_SECONDS = 7 * 24 * 3600


@login_required(login_url='login')
@staff_or_branch_admin_required
def generate_history_link(request, customer_id):
    """
    Admin action: generate a signed, expiring link for this customer.
    Returns JSON: { link: "https://..." }
    """
    customer = get_object_or_404(Customer, id=customer_id)
    signer = TimestampSigner(salt=SIGNER_SALT)
    token = signer.sign(str(customer.id))
    url = request.build_absolute_uri(
        reverse('customer_history_access', args=[token])
    )
    messages.success(request, f"Link for {customer.user.get_full_name()} created.")
    return redirect('')


def customer_history_access(request, customer_phone):
    user = get_object_or_404(CustomUser, phone_number=customer_phone)
    customer = get_object_or_404(Customer, user=user)
    orders = ServiceRenderedOrder.objects.filter(customer=customer, status__in=['completed', 'onCredit']).order_by(
        '-date')

    return render(request, 'layouts/customers/customer_access_history.html', {
        'customer': customer,
        'orders': orders,
    })
