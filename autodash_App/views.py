import base64
import json
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.functions import TruncDate
from django.http import (
    JsonResponse
)
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import models, forms
from .forms import (
    LogServiceForm, BranchForm, ExpenseForm, EnrollWorkerForm, CreateCustomerForm,
    CreateVehicleForm
)
from .helper import send_sms
from .models import (
    CustomerSubscription, CustomUser,
    Service, LoyaltyTransaction, VehicleGroup, ProductSale, ProductCategory,
    Subscription, WorkerCategory
)
from .models import (
    DailyExpenseBudget
)


@login_required(login_url='login')
def home(request):
    """
    Main dashboard
    ...
    """
    user = request.user
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    # ----------------------------- ADMIN FLOW -----------------------------
    if user.is_staff or user.is_superuser:
        branch_id = request.GET.get('branch_id')
        if not branch_id:
            # Force admin to select a branch
            branches = Branch.objects.all()
            return render(request, 'layouts/admin/select_branch.html', {'branches': branches})

        branch = get_object_or_404(Branch, id=branch_id)

        # Number of days param
        days_param = request.GET.get('days', '10')
        try:
            days = int(days_param)
            if days < 1:
                days = 10
        except ValueError:
            days = 10
        start_date = today - timedelta(days=days)

        # Expense range
        start_days_ago = request.GET.get('start_days_ago', '20')
        end_days_ago = request.GET.get('end_days_ago', '10')
        try:
            start_days_ago = int(start_days_ago)
            end_days_ago = int(end_days_ago)
            if start_days_ago < 0:
                start_days_ago = 20
            if end_days_ago < 0:
                end_days_ago = 10
            if end_days_ago > start_days_ago:
                end_days_ago = start_days_ago
        except ValueError:
            start_days_ago = 20
            end_days_ago = 10

        expense_start_date = today - timedelta(days=start_days_ago)
        expense_end_date = today - timedelta(days=end_days_ago)

        # 1) Daily expenses & budget
        expenses_today = Expense.objects.filter(branch=branch, date=today) \
                             .aggregate(total=Sum('amount'))['total'] or 0
        daily_budget_obj = DailyExpenseBudget.objects.filter(branch=branch, date=today).first()
        daily_expense_budget = daily_budget_obj.budgeted_amount if daily_budget_obj else 0
        expenses_over_budget = expenses_today > daily_expense_budget
        budget_difference = abs(expenses_today - daily_expense_budget)

        # 2) Daily revenue, profit
        revenue_today = Revenue.objects.filter(branch=branch, date=today) \
                            .aggregate(total=Sum('final_amount'))['total'] or 0
        revenue_yesterday = Revenue.objects.filter(branch=branch, date=yesterday) \
                                .aggregate(total=Sum('final_amount'))['total'] or 0
        profit_today = revenue_today - expenses_today

        # % increase from yesterday's revenue
        if revenue_yesterday > 0:
            percentage_increase = ((revenue_today - revenue_yesterday) / revenue_yesterday) * 100
        else:
            percentage_increase = 0
        percentage_increase = round(percentage_increase, 2)

        # 3) Services rendered today
        services_rendered_today = ServiceRenderedOrder.objects.filter(
            branch=branch, date__date=today, status='completed'
        ).count()
        services_rendered_yesterday = ServiceRenderedOrder.objects.filter(
            branch=branch, date__date=yesterday, status='completed'
        ).count()
        if services_rendered_yesterday > 0:
            services_percentage_change = (
                (services_rendered_today - services_rendered_yesterday)
                / services_rendered_yesterday
            ) * 100
        else:
            services_percentage_change = 0
        services_percentage_change = round(services_percentage_change, 2)

        # 4) Commission today
        total_commission = Commission.objects.filter(worker__branch=branch, date=today) \
                               .aggregate(total=Sum('amount'))['total'] or 0
        commission_today = total_commission  # alias

        # 5) Products sold summary (standalone product sales from `ProductSale`)
        products_purchased_qs = ProductSale.objects.filter(
            branch=branch,
            date_sold__date=today
        )
        products_sold_today = products_purchased_qs.aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
        products_sold_amount_today = products_purchased_qs.aggregate(sum_amt=Sum('total_price'))['sum_amt'] or 0

        # 6) "Gross sales"
        # If Revenue includes all service + product, then keep as is
        # Otherwise: gross_sales = revenue_today + products_sold_amount_today
        gross_sales = revenue_today

        # 7) Net sales => define your logic
        # Possibly profit_today - commission or something else
        net_sales = profit_today - total_commission

        # 8) Product categories sold (today) => breakdown
        # We group by product.category in `ProductSale`
        category_aggregate = products_purchased_qs.values('product__category').annotate(
            cat_qty=Sum('quantity'),
            cat_amt=Sum('total_price')
        )

        # Build a list of dicts with category ID, name, total_qty, total_amount
        product_categories_today = []
        for row in category_aggregate:
            cat_id = row['product__category']
            cat_qty = row['cat_qty'] or 0
            cat_amt = row['cat_amt'] or 0

            cat_name = "Uncategorized"
            if cat_id:
                try:
                    cat_obj = ProductCategory.objects.get(id=cat_id)
                    cat_name = cat_obj.name
                except ProductCategory.DoesNotExist:
                    pass

            product_categories_today.append({
                "category_id": cat_id,
                "category_name": cat_name,
                "total_qty": cat_qty,
                "total_amount": cat_amt
            })

        # Summation across all categories => for the "Category Totals" card
        product_category_total_qty = sum(item['total_qty'] for item in product_categories_today)
        product_category_total_amt = sum(item['total_amount'] for item in product_categories_today)

        # 9) Recent & pending services
        recent_services = ServiceRenderedOrder.objects.filter(branch=branch).order_by('-date')[:5]
        pending_services = ServiceRenderedOrder.objects.filter(branch=branch, status='pending').order_by('-date')

        # 10) Order status counts
        total_orders = ServiceRenderedOrder.objects.filter(branch=branch).count()
        completed_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='completed').count()
        pending_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='pending').count()
        canceled_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='canceled').count()
        on_credit_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='onCredit').count()

        # 11) Worker stats in the past N days
        workers_qs = Worker.objects.filter(branch=branch)
        services_by_worker = workers_qs.annotate(
            total_services=Count(
                'servicerenderedorder',
                filter=Q(servicerenderedorder__date__gte=start_date, servicerenderedorder__status='completed')
            )
        ).order_by('-total_services')

        commission_by_worker = workers_qs.annotate(
            total_commission=Sum(
                'commissions__amount',
                filter=Q(commissions__date__gte=start_date)
            )
        ).order_by('-total_commission')

        # 12) Expenses in range
        expenses_in_range = Expense.objects.filter(
            branch=branch,
            date__range=[expense_end_date, expense_start_date]
        ).order_by('-date')
        total_expenses_in_range = expenses_in_range.aggregate(total=Sum('amount'))['total'] or 0

        # Days options
        days_options = [5, 10, 15, 30, 60, 90]

        # daily logs
        daily_revenues = Revenue.objects.filter(branch=branch, date=datetime.now()) \
                                        .select_related('service_rendered', 'user')
        daily_expenses = Expense.objects.filter(branch=branch, date=datetime.now()) \
                                        .select_related('user')
        daily_commissions = Commission.objects.filter(worker__branch=branch, date=datetime.now()) \
                                              .select_related('worker', 'service_rendered')

        context = {
            'is_admin': True,
            'branch': branch,

            # Expenses
            'expenses_today': expenses_today,
            'daily_expense_budget': daily_expense_budget,
            'expenses_over_budget': expenses_over_budget,
            'budget_difference': budget_difference,

            # Revenue, profit
            'revenue_today': revenue_today,
            'profit_today': profit_today,
            'percentage_increase': percentage_increase,

            # Services
            'services_rendered_today': services_rendered_today,
            'services_percentage_change': services_percentage_change,

            # Commission
            'total_commission': total_commission,
            'commission_today': commission_today,

            # Products
            'products_sold_today': products_sold_today,
            'products_sold_amount_today': products_sold_amount_today,

            # Cards layout
            'gross_sales': gross_sales,
            'net_sales': net_sales,
            'product_category_total_qty': product_category_total_qty,
            'product_category_total_amt': product_category_total_amt,

            # Breakdown list for modal
            'product_categories_today': product_categories_today,

            # Service orders
            'recent_services': recent_services,
            'pending_services': pending_services,
            'total_orders': total_orders,
            'completed_orders_count': completed_orders_count,
            'pending_orders_count': pending_orders_count,
            'canceled_orders_count': canceled_orders_count,
            'on_credit_orders_count': on_credit_orders_count,

            # Worker stats
            'services_by_worker': services_by_worker,
            'commission_by_worker': commission_by_worker,
            'days_options': days_options,
            'days': days,

            # Expense range
            'start_days_ago': start_days_ago,
            'end_days_ago': end_days_ago,
            'expense_start_date': expense_start_date,
            'expense_end_date': expense_end_date,
            'expenses_in_range': expenses_in_range,
            'total_expenses_in_range': total_expenses_in_range,

            # daily logs
            'daily_revenues': daily_revenues,
            'daily_expenses': daily_expenses,
            'daily_commissions': daily_commissions,
        }
        return render(request, 'layouts/admin/dashboard.html', context)

    # ----------------------------- WORKER FLOW -----------------------------
    else:
        try:
            worker = Worker.objects.get(user=user)
        except Worker.DoesNotExist:
            messages.error(request, 'No worker profile found.')
            return redirect('logout')

        branch = worker.branch

        # Worker-specific stats
        worker_commission_today = Commission.objects.filter(worker=worker, date=today) \
                                      .aggregate(total=Sum('amount'))['total'] or 0
        services_rendered_today = ServiceRenderedOrder.objects.filter(
            workers=worker,
            date__date=today
        ).count()
        products_sold_today = ProductPurchased.objects.filter(
            service_order__branch=branch,
            service_order__date__date=today
        ).aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
        recent_services = ServiceRenderedOrder.objects.filter(
            workers=worker
        ).distinct().order_by('-date')[:5]
        pending_services = ServiceRenderedOrder.objects.filter(
            status='pending',
            workers=worker
        ).distinct().order_by('-date')
        average_rating = worker.average_rating()

        # Branch-wide daily stats
        revenue_today = Revenue.objects.filter(branch=branch, date=today) \
                            .aggregate(total=Sum('final_amount'))['total'] or 0
        expenses_today = Expense.objects.filter(branch=branch, date=today) \
                             .aggregate(total=Sum('amount'))['total'] or 0
        profit_today = revenue_today - expenses_today

        # Compare revenue to yesterday
        revenue_yesterday = Revenue.objects.filter(branch=branch, date=yesterday) \
                                .aggregate(total=Sum('final_amount'))['total'] or 0
        if revenue_yesterday > 0:
            revenue_change_percentage = ((revenue_today - revenue_yesterday) / revenue_yesterday) * 100
        else:
            revenue_change_percentage = 0
        revenue_change_percentage = round(revenue_change_percentage, 2)

        # Daily budget
        daily_budget_obj = DailyExpenseBudget.objects.filter(branch=branch, date=today).first()
        daily_expense_budget = daily_budget_obj.budgeted_amount if daily_budget_obj else 0
        expenses_over_budget = expenses_today > daily_expense_budget
        budget_difference = abs(expenses_today - daily_expense_budget)

        # Branch order status counts
        total_orders = ServiceRenderedOrder.objects.filter(branch=branch).count()
        completed_orders_count = ServiceRenderedOrder.objects.filter(
            branch=branch, status='completed'
        ).count()
        pending_orders_count = ServiceRenderedOrder.objects.filter(
            branch=branch, status='pending'
        ).count()
        canceled_orders_count = ServiceRenderedOrder.objects.filter(
            branch=branch, status='canceled'
        ).count()
        on_credit_orders_count = ServiceRenderedOrder.objects.filter(
            branch=branch, status='onCredit'
        ).count()

        full_stars = int(average_rating)  # number of full stars
        has_half_star = (average_rating - full_stars) >= 0.5
        empty_stars = 5 - full_stars - (1 if has_half_star else 0)

        context = {
            'is_admin': False,
            'worker': worker,
            'branch': branch,
            'worker_commission_today': worker_commission_today,
            'services_rendered_today': services_rendered_today,
            'products_sold_today': products_sold_today,
            'recent_services': recent_services,
            'pending_services': pending_services,
            'average_rating': average_rating,
            'full_stars_list': range(full_stars),  # e.g. range(4) if rating is 4.2
            'has_half_star': has_half_star,  # True
            'empty_stars_list': range(empty_stars),

            # Branch-wide
            'revenue_today': revenue_today,
            'expenses_today': expenses_today,
            'profit_today': profit_today,
            'revenue_change_percentage': revenue_change_percentage,
            'daily_expense_budget': daily_expense_budget,
            'expenses_over_budget': expenses_over_budget,
            'budget_difference': budget_difference,

            # Status counts
            'total_orders': total_orders,
            'completed_orders_count': completed_orders_count,
            'pending_orders_count': pending_orders_count,
            'canceled_orders_count': canceled_orders_count,
            'on_credit_orders_count': on_credit_orders_count,
        }
        # Use a separate worker template
        return render(request, 'layouts/workers/worker_dashboard.html', context)


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
        if form.is_valid():
            customer = form.cleaned_data['customer']
            vehicle = form.cleaned_data['vehicle']
            selected_services = form.cleaned_data['service']
            selected_workers = form.cleaned_data['workers']
            selected_products = form.cleaned_data.get('products', [])
            product_quantities = request.POST.getlist('product_quantity')

            # 1) Sum up the services using standard (non-negotiated) price only
            total_services = 0
            for svc in selected_services:
                total_services += svc.price

            # 2) Sum up any products selected
            total_products = 0
            products_purchased = []
            for product, qty_str in zip(selected_products, product_quantities):
                qty = int(qty_str) if qty_str.isdigit() else 1
                if product.stock < qty:
                    messages.error(request, f'Not enough stock for {product.name}.')
                    return redirect('log_service')
                total_price = product.price * qty
                total_products += total_price
                products_purchased.append((product, qty, total_price))

            total = total_services + total_products

            # 3) Create the ServiceRenderedOrder with status 'pending'
            new_order = ServiceRenderedOrder.objects.create(
                customer=customer,
                user=user,
                total_amount=total,
                final_amount=total,
                vehicle=vehicle,
                branch=worker.branch,
                status='pending'
            )
            new_order.workers.set(selected_workers)

            # 4) Create ServiceRendered entries (negotiated_price=None initially)
            for svc in selected_services:
                sr = ServiceRendered.objects.create(
                    service=svc,
                    order=new_order,
                    negotiated_price=None  # We'll handle at confirm time if negotiable
                )
                sr.workers.set(selected_workers)

            # 5) Create ProductPurchased entries
            for product, qty, total_price in products_purchased:
                ProductPurchased.objects.create(
                    service_order=new_order,
                    product=product,
                    quantity=qty,
                    total_price=total_price
                )
                # Decrement stock
                product.stock -= qty
                product.save()

            # 6) Optional SMS
            phone = customer.user.phone_number
            if phone:
                msg = (
                    f"Hello {customer.user.first_name}, "
                    f"your service #{new_order.service_order_number} is pending at {timezone.now():%Y-%m-%d %H:%M}. "
                    f"We will update you soon."
                )
                try:
                    print("Sending SMS:", msg)
                    # send_sms(phone, msg)
                except Exception as e:
                    print("SMS error:", e)

            messages.success(request, 'Service logged successfully (status=pending).')
            return redirect('confirm_service_rendered', pk=new_order.pk)
        else:
            messages.error(request, "Form is invalid. Please correct the errors.")
    else:
        form = LogServiceForm(branch=worker.branch)

    products = Product.objects.filter(branch=worker.branch)
    vehicle_groups = VehicleGroup.objects.all()

    context = {
        'form': form,
        'products': products,
        'vehicle_groups': vehicle_groups
    }
    return render(request, 'layouts/workers/log_service.html', context)



@login_required(login_url='login')
@transaction.atomic
def confirm_service(request, pk):
    """
    Handles finalizing a service order:
      - Allows the user to set negotiated_price for negotiable services on this page.
      - Allocates/removes commission depending on the new status.
      - For loyalty or subscription-covered services => record an Expense for that commission.
      - If leftover is actually paid => record Revenue.
      - If onCredit => create Arrears, and record commission expense for the entire order.
      - Sends SMS with receipt details, plus a feedback link if completed/onCredit.
    """

    # A helper to fetch the price: either the negotiated_price (if set) or the base service price
    def get_sr_price(sr):
        return sr.negotiated_price if sr.negotiated_price is not None else sr.service.price

    user = request.user
    worker = get_object_or_404(Worker, user=user)
    service_order = get_object_or_404(ServiceRenderedOrder, pk=pk)

    # All services tied to this order
    services_rendered = service_order.rendered.all()
    customer = service_order.customer
    phone_number = customer.user.phone_number if customer else None

    # Attempt to see if the customer has a subscription
    try:
        cust_sub = CustomerSubscription.objects.filter(customer=customer).latest('end_date')
        subscription_active = cust_sub.is_active()
    except CustomerSubscription.DoesNotExist:
        cust_sub = None
        subscription_active = False

    if request.method == 'GET':
        # Identify which services might be covered by the subscription
        covered_by_subscription = []
        if subscription_active and service_order.vehicle:
            for sr in services_rendered:
                if (
                    sr.service in cust_sub.subscription.services.all()
                    and service_order.vehicle.vehicle_group in cust_sub.subscription.vehicle_group.all()
                ):
                    covered_by_subscription.append(sr.id)

        # If you have products to display or add
        from .models import Product  # or wherever Product is defined
        available_products = Product.objects.filter(branch=worker.branch)

        context = {
            'service_order': service_order,
            'services_rendered': services_rendered,
            'loyalty_points': customer.loyalty_points,
            'available_products': available_products,
            'subscription_active': subscription_active,
            'cust_sub': cust_sub,
            'covered_by_subscription': covered_by_subscription,
        }
        return render(request, 'layouts/workers/confirm_service_order.html', context)

    # ------------------ POST: Finalize the order ------------------
    old_status = service_order.status
    new_status = request.POST.get('status', 'completed')
    payment_method = request.POST.get('payment_method', 'cash')

    # 1) Parse negotiated prices for each negotiable service
    for sr in services_rendered:
        if sr.service.category and sr.service.category.negotiable:
            field_name = f"negotiated_price_{sr.id}"
            raw_value = request.POST.get(field_name, "")
            try:
                nego_price = float(raw_value)
            except (ValueError, TypeError):
                nego_price = 0.0

            if nego_price <= 0:
                messages.error(
                    request,
                    f"You must provide a valid negotiated price for {sr.service.service_type}"
                )
                return redirect('confirm_service_rendered', pk=service_order.pk)

            # Update the negotiable service with the user-provided price
            sr.negotiated_price = nego_price
            sr.save()

    # 2) Update the order status & payment method
    service_order.status = new_status
    service_order.payment_method = payment_method
    service_order.save()

    # 3) Commission allocation/removal for the entire order
    if new_status in ['completed', 'onCredit'] and old_status != new_status:
        # Allocate commission
        for sr in services_rendered:
            sr.allocate_commission()
    elif old_status in ['completed', 'onCredit'] and new_status in ['pending', 'canceled']:
        # Remove commission
        for sr in services_rendered:
            sr.remove_commission()

    # 4) Calculate base totals using negotiated or standard price
    total_services_price = sum(get_sr_price(sr) for sr in services_rendered)
    total_products_price = sum(p.total_price for p in service_order.products_purchased.all())
    recalculated_total = total_services_price + total_products_price

    # 5) Check subscription coverage
    subscription_covered_ids = []
    if subscription_active and service_order.vehicle:
        for sr in services_rendered:
            if (
                sr.service in cust_sub.subscription.services.all()
                and service_order.vehicle.vehicle_group in cust_sub.subscription.vehicle_group.all()
            ):
                subscription_covered_ids.append(sr.id)

    # Subtract subscription-covered services
    for sr in services_rendered:
        if sr.id in subscription_covered_ids:
            recalculated_total -= get_sr_price(sr)

    # 6) Identify loyalty redemption
    redeem_service_ids = []
    for sr in services_rendered:
        if f'redeem_service_{sr.id}' in request.POST:
            redeem_service_ids.append(sr.id)

    loyalty_points_needed = 0
    for sr in services_rendered:
        # If user wants to redeem loyalty AND not subscription-covered
        if sr.id in redeem_service_ids and sr.id not in subscription_covered_ids:
            recalculated_total -= get_sr_price(sr)
            loyalty_points_needed += sr.service.loyalty_points_required

    if recalculated_total < 0:
        recalculated_total = 0

    # 7) Apply discount
    discount_type = request.POST.get('discount_type', 'amount')
    discount_value_str = request.POST.get('discount_value', '0')
    try:
        discount_value = float(discount_value_str)
    except ValueError:
        discount_value = 0.0
    discount_value = max(discount_value, 0)

    if discount_type == 'percentage':
        discount_value = min(discount_value, 100)
        discount_amount = (recalculated_total * discount_value) / 100.0
    else:
        discount_amount = min(discount_value, recalculated_total)

    recalculated_total -= discount_amount
    if recalculated_total < 0:
        recalculated_total = 0

    # 8) Save final amount
    service_order.final_amount = recalculated_total
    service_order.discount_type = discount_type
    service_order.discount_value = discount_value
    service_order.save()

    leftover = recalculated_total  # portion actually paid in real money

    # 9) Deduct loyalty for redeemed services
    if loyalty_points_needed > 0:
        if customer.loyalty_points >= loyalty_points_needed:
            customer.loyalty_points -= loyalty_points_needed
            LoyaltyTransaction.objects.create(
                customer=customer,
                points=-loyalty_points_needed,
                transaction_type='redeem',
                description=f"Redeemed {len(redeem_service_ids)} service(s) with loyalty",
                branch=service_order.branch,
            )
        else:
            messages.warning(request, "Not enough points to redeem selected services.")

    # If entire payment is 'loyalty', subtract leftover from loyalty again
    if payment_method == 'loyalty':
        points_to_use = min(customer.loyalty_points, leftover)
        leftover -= points_to_use
        customer.loyalty_points -= points_to_use
        if points_to_use > 0:
            LoyaltyTransaction.objects.create(
                customer=customer,
                points=-points_to_use,
                transaction_type='redeem',
                description=(
                    f"Final payment coverage for {service_order.service_order_number}"
                ),
                branch=service_order.branch,
            )
    customer.save()

    # 10) If onCredit => leftover => Arrears, plus commission expense
    from .models import Expense, Arrears  # or wherever these are
    if new_status == 'onCredit':
        if not hasattr(service_order, 'arrears'):
            Arrears.objects.create(
                service_order=service_order,
                branch=service_order.branch,
                amount_owed=leftover
            )
        # Commission expense for onCredit
        total_commission = Commission.objects.filter(
            service_rendered__order=service_order
        ).aggregate(sum=Sum('amount'))['sum'] or 0
        Expense.objects.create(
            branch=service_order.branch,
            description=f"Commission expense for onCredit {service_order.service_order_number}",
            amount=total_commission,
            user=user
        )
        # No revenue because leftover not paid

    # 11) If completed => leftover might be real payment => create Revenue
    elif new_status == 'completed':
        from .models import Revenue
        if payment_method in [
            'cash',
            'momo',
            'subscription-cash',
            'subscription-momo',
            'loyalty-cash'
        ]:
            if leftover > 0:
                has_revenue = Revenue.objects.filter(service_rendered=service_order).exists()
                if not has_revenue:
                    Revenue.objects.create(
                        service_rendered=service_order,
                        branch=service_order.branch,
                        amount=leftover,
                        final_amount=leftover,
                        user=user
                    )
        elif payment_method == 'loyalty':
            # leftover should be 0 => no direct revenue
            # entire order's commissions => expense
            total_commission = Commission.objects.filter(
                service_rendered__order=service_order
            ).aggregate(sum=Sum('amount'))['sum'] or 0
            Expense.objects.create(
                branch=service_order.branch,
                description=(
                    f"Loyalty coverage commission expense for {service_order.service_order_number}"
                ),
                amount=total_commission,
                user=user
            )
        elif payment_method == 'subscription':
            # leftover should be 0 => no direct revenue
            # entire order's commissions => expense
            total_commission = Commission.objects.filter(
                service_rendered__order=service_order
            ).aggregate(sum=Sum('amount'))['sum'] or 0
            Expense.objects.create(
                branch=service_order.branch,
                description=(
                    f"Subscription coverage commission expense for {service_order.service_order_number}"
                ),
                amount=total_commission,
                user=user
            )

    # 12) Earn loyalty if newly completed
    if new_status == 'completed':
        for sr in services_rendered:
            pts = sr.service.loyalty_points_earned
            if pts > 0:
                LoyaltyTransaction.objects.create(
                    customer=customer,
                    points=pts,
                    transaction_type='gain',
                    description=f"Points earned for {sr.service.service_type}",
                    branch=service_order.branch,
                )
                customer.loyalty_points += pts
        customer.save()

    # 13) Commission expense for loyalty/subscription services
    if new_status in ['completed', 'onCredit']:
        for sr in services_rendered:
            if sr.id in redeem_service_ids or sr.id in subscription_covered_ids:
                sr_commission = sr.commissions.aggregate(sum=Sum('amount'))['sum'] or 0
                if sr_commission > 0:
                    Expense.objects.create(
                        branch=service_order.branch,
                        description=(
                            f"Commission expense for "
                            f"{'loyalty' if sr.id in redeem_service_ids else 'subscription'} "
                            f"service on {service_order.service_order_number}"
                        ),
                        amount=sr_commission,
                        user=user
                    )

    # 14) Optional: Send SMS
    if phone_number:
        if new_status == 'pending':
            txt = (
                f"Hello {customer.user.first_name}, your service #{service_order.service_order_number} "
                f"is now pending."
            )
            print(txt)

        elif new_status == 'canceled':
            txt = (
                f"Hello {customer.user.first_name}, your service #{service_order.service_order_number} "
                f"has been canceled."
            )
            print(txt)

        elif new_status in ['completed', 'onCredit']:
            # Build textual receipt
            service_lines = []
            for sr in services_rendered:
                actual_price = get_sr_price(sr)
                service_lines.append(f"{sr.service.service_type} - GHS {actual_price:.2f}")

            product_lines = []
            for prod_item in service_order.products_purchased.all():
                product_lines.append(
                    f"{prod_item.product.name} x{prod_item.quantity} => GHS {prod_item.total_price:.2f}"
                )

            lines = [
                f"Receipt for Service #{service_order.service_order_number}",
                f"Final Amount: GHS {service_order.final_amount:.2f}",
            ]
            if service_lines:
                lines.append("Services:")
                lines.extend(service_lines)
            if product_lines:
                lines.append("Products:")
                lines.extend(product_lines)
            lines.append("Thank you for choosing us!")
            receipt_text = "\n".join(lines)
            print(receipt_text)

            # Feedback link
            from django.urls import reverse
            feedback_url = request.build_absolute_uri(
                reverse('service_feedback', args=[service_order.id])
            )
            feedback_msg = (
                f"Hello {customer.user.first_name}, your service #{service_order.service_order_number} "
                f"is now {new_status}. Kindly leave feedback here: {feedback_url}"
            )
            print(feedback_msg)

    messages.success(request, f"Service updated to {new_status}.")
    if new_status in ['completed', 'onCredit']:
        return redirect('service_receipt', pk=service_order.pk)
    return redirect('index')


@login_required(login_url='login')
def service_receipt(request, pk):
    # Fetch the order
    service_order = get_object_or_404(ServiceRenderedOrder, pk=pk)
    services_rendered = service_order.rendered.all()
    products_purchased = service_order.products_purchased.all()

    # If you need the negotiated price or normal price:
    def get_sr_price(sr):
        return sr.negotiated_price if sr.negotiated_price is not None else sr.service.price

    # Summaries
    total_services_price = sum(get_sr_price(sr) for sr in services_rendered)
    total_products_price = sum(p.total_price for p in products_purchased)
    final_amount = service_order.final_amount or 0
    workers = service_order.workers.all()

    context = {
        'service_order': service_order,
        'services_rendered': services_rendered,
        'products_purchased': products_purchased,
        'total_services_price': total_services_price,
        'total_products_price': total_products_price,
        'final_amount': final_amount,
        'workers': workers
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
        selected_products = request.POST.getlist('selected_products')
        customer_phone = request.POST.get('customer_phone', '').strip()

        if not selected_products:
            messages.error(request, "No products selected.")
            return redirect('sell_product')

        batch_id = uuid.uuid4()
        batch_date = timezone.now()
        sales_lines = []

        try:
            with transaction.atomic():
                # 1) Create ProductSale rows
                for product_id in selected_products:
                    product = Product.objects.get(id=product_id, branch=branch)
                    quantity_str = request.POST.get(f'quantity_{product_id}', '1')
                    quantity = int(quantity_str) if quantity_str.isdigit() else 1

                    if product.stock < quantity:
                        raise ValueError(f'Not enough stock for {product.name}')

                    sale = ProductSale.objects.create(
                        user=request.user,
                        batch_id=batch_id,
                        product=product,
                        branch=branch,
                        quantity=quantity,
                        total_price=product.price * quantity,
                        date_sold=batch_date
                    )
                    sales_lines.append(sale)

                    # Update stock
                    product.stock -= quantity
                    product.save()

                # 2) Create a Revenue record for total of all items in this batch
                total_price = sum(s.total_price for s in sales_lines)
                Revenue.objects.create(
                    branch=branch,
                    amount=total_price,
                    final_amount=total_price,
                    user=user
                )

                # 3) (Optional) send SMS
                if customer_phone:
                    message_lines = [f"Receipt from Autodash({branch.name}):"]
                    for s in sales_lines:
                        message_lines.append(f"{s.quantity}x {s.product.name} => GHS {s.total_price:.2f}")
                    message_lines.append(f"Total: GHS {total_price:.2f}")
                    message_lines.append("Thank you for your purchase!")

                    sms_message = "\n".join(message_lines)

                    try:
                        send_sms(customer_phone, sms_message)
                    except Exception as sms_err:
                        messages.warning(request, f"SMS not sent: {sms_err}")

                messages.success(request, "Sale recorded successfully.")
                return redirect('sell_product')

        except Exception as e:
            messages.error(request, str(e))
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
    """
    service_order = get_object_or_404(ServiceRenderedOrder, id=pk)
    services_under_service_order = ServiceRendered.objects.filter(order=service_order)

    # If feedback & rating are already provided
    if service_order.customer_feedback and service_order.customer_rating:
        messages.success(request, 'Your feedback has already been recorded.')

    if request.method == 'POST':
        rating = request.POST.get('rating')
        feedback = request.POST.get('feedback')

        service_order.customer_rating = rating
        service_order.customer_feedback = feedback
        service_order.save()

        # Update worker ratings
        for w in service_order.workers.all():
            w.add_rating(int(rating))
            w.save()

        messages.success(request, 'Your feedback has been recorded.')
        return redirect('thank_you_for_feedback', pk=service_order.id)

    context = {
        'service_order': service_order,
        'services': services_under_service_order,
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


@login_required(login_url='login')
def service_history(request):
    user = request.user

    # Must be worker, admin, or staff
    if user.role not in ["worker", "Admin"] and not user.is_staff:
        messages.error(request, "You are not authorized to view this page.")
        return redirect('index')

    # Prepare base queryset
    services_rendered = ServiceRenderedOrder.objects.all().order_by('-date')

    # If user is a worker (not staff), filter by that worker's branch
    if not user.is_staff and not user.is_superuser:
        try:
            worker = Worker.objects.get(user=user)
        except Worker.DoesNotExist:
            messages.error(request, "No worker profile found.")
            return redirect('index')
        services_rendered = services_rendered.filter(branch=worker.branch)

    # Filters
    statuses = ServiceRenderedOrder.STATUS_CHOICES
    payment_methods = ['all', 'cash', 'momo', 'loyalty', 'subscription', 'subscription-cash', 'subscription-momo']
    # You can add more if you have them in your code

    status_filter = request.GET.get('status', 'all')
    payment_filter = request.GET.get('payment_method', 'all')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    # If user is staff/superuser, allow branch filter
    branches = None
    selected_branch_id = None
    if user.is_staff or user.is_superuser:
        branches = Branch.objects.all()
        selected_branch_id = request.GET.get('branch', '')
        if selected_branch_id:
            services_rendered = services_rendered.filter(branch_id=selected_branch_id)

    # 1) Status filter
    if status_filter != 'all':
        services_rendered = services_rendered.filter(status=status_filter)

    # 2) Payment filter
    if payment_filter != 'all':
        services_rendered = services_rendered.filter(payment_method=payment_filter)

    # 3) Date range filter
    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        else:
            start_date = None

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            end_date = None

        if start_date and end_date:
            # Filter by date range
            services_rendered = services_rendered.filter(
                date__date__gte=start_date.date(),
                date__date__lte=end_date.date()
            )
        elif start_date and not end_date:
            services_rendered = services_rendered.filter(
                date__date__gte=start_date.date()
            )
        elif end_date and not start_date:
            services_rendered = services_rendered.filter(
                date__date__lte=end_date.date()
            )
    except ValueError:
        messages.warning(request, "Invalid date format for start/end date. Ignoring date filters.")

    # Bulk status update logic
    if request.method == 'POST':
        selected_order_ids = request.POST.getlist('selected_orders')
        new_status = request.POST.get('new_status')
        valid_statuses = [choice[0] for choice in ServiceRenderedOrder.STATUS_CHOICES]

        if selected_order_ids and new_status in valid_statuses:
            for order_id in selected_order_ids:
                order = get_object_or_404(ServiceRenderedOrder, id=order_id)
                old_status = order.status

                if old_status == new_status:
                    continue

                # 1) If changing to completed or onCredit => allocate commissions
                if old_status not in ['completed', 'onCredit'] and new_status in ['completed', 'onCredit']:
                    for sr in order.rendered.all():
                        sr.allocate_commission()

                # 2) If reverting from completed/onCredit to pending/canceled => remove commissions
                elif old_status in ['completed', 'onCredit'] and new_status in ['pending', 'canceled']:
                    for sr in order.rendered.all():
                        sr.remove_commission()

                # Update the order’s status
                order.status = new_status
                order.save()

                # 3) OnCredit => create Arrears if needed, record commission expense
                if new_status == 'onCredit':
                    if not hasattr(order, 'arrears'):
                        Arrears.objects.create(
                            service_order=order,
                            branch=order.branch,
                            amount_owed=order.final_amount or 0
                        )
                    # Commission expense
                    total_commission_allocated = Commission.objects.filter(
                        service_rendered__order=order
                    ).aggregate(total=Sum('amount'))['total'] or 0
                    Expense.objects.create(
                        branch=order.branch,
                        description=f"Commission expense for onCredit {order.service_order_number}",
                        amount=total_commission_allocated,
                        user=request.user
                    )

            messages.success(request, "Selected orders have been updated.")
            return redirect('service_history')
        else:
            messages.error(request, "Please select orders and a valid status to update.")

    context = {
        'services_rendered': services_rendered,
        'statuses': statuses,
        'status_filter': status_filter,
        'payment_methods': payment_methods,
        'payment_filter': payment_filter,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'branches': branches,
        'selected_branch_id': selected_branch_id,
    }
    return render(request, 'layouts/workers/service_history.html', context)


# ----------------------------------------------------------------
#                       CUSTOMER VIEWS
# ----------------------------------------------------------------

@login_required(login_url='login')
def customer_dashboard(request):
    """
    Dashboard for a customer user: shows recent services, active subscription,
    loyalty points, transactions, and their vehicles.
    """
    customer = get_object_or_404(Customer, user=request.user)
    services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')[:5]
    active_subscription = CustomerSubscription.objects.filter(
        customer=customer,
        end_date__gte=timezone.now()
    ).first()
    loyalty_points = customer.loyalty_points
    loyalty_transactions = LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')[:5]
    vehicles = CustomerVehicle.objects.filter(customer=customer)

    context = {
        'customer': customer,
        'services_rendered': services_rendered,
        'active_subscription': active_subscription,
        'loyalty_points': loyalty_points,
        'loyalty_transactions': loyalty_transactions,
        'vehicles': vehicles,
    }
    return render(request, 'layouts/customers/customer_index.html', context)


@login_required(login_url='login')
def customer_service_history(request):
    """
    Shows a customer's own service history.
    """
    user = get_object_or_404(CustomUser, id=request.user.id)
    customer = get_object_or_404(Customer, user=user)
    services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')[:20]

    return render(
        request,
        'layouts/customers/service_history.html',
        {'services_rendered': services_rendered}
    )


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


@staff_member_required
def manage_workers(request):
    """
    Allows an admin to view and manage all workers or filter by branch and category.
    """
    branch_id = request.GET.get('branch', '')
    category_id = request.GET.get('category', '')

    workers = Worker.objects.all()

    # If branch filter is selected
    if branch_id:
        workers = workers.filter(branch_id=branch_id)

    # If category filter is selected
    if category_id:
        workers = workers.filter(worker_category_id=category_id)

    branches = Branch.objects.all()
    categories = WorkerCategory.objects.all()

    context = {
        'workers': workers,
        'branches': branches,
        'categories': categories,           # pass categories to template
        'selected_branch': branch_id,       # remember which branch is chosen
        'selected_category': category_id,   # remember which category is chosen
    }
    return render(request, 'layouts/admin/manage_workers.html', context)


# views.py
@staff_member_required
def approve_worker(request, worker_id):
    worker = get_object_or_404(Worker, id=worker_id)
    user = worker.user
    user.approved = True
    user.save()
    messages.success(request, f"Worker account approved for {worker.user.get_full_name()}.")
    return redirect('manage_workers')


@staff_member_required
def worker_detail(request, worker_id):
    """
    Admin view to see details of a specific worker, with optional unapproval or delete actions.
    """
    worker = get_object_or_404(Worker, id=worker_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'unapprove':
            worker.is_gh_card_approved = False
            worker.save()
            messages.success(request, 'Worker has been unapproved.')
            return redirect('worker_detail', worker_id=worker.id)
        elif action == 'delete':
            worker.user.delete()
            messages.success(request, 'Worker has been deleted.')
            return redirect('manage_workers')

    context = {'worker': worker}
    return render(request, 'layouts/admin/worker_detail.html', context)


@staff_member_required
def manage_customers(request):
    """
    Admin view to:
      - Filter customers by branch,
      - Reassign a customer's branch,
      - Send an SMS to the customer.
    """
    # 1) Branch filter from GET
    branch_id = request.GET.get('branch', '')
    if branch_id:
        customers_qs = Customer.objects.filter(branch_id=branch_id)
    else:
        customers_qs = Customer.objects.all()

    branches = Branch.objects.all()

    # 2) Handle POST actions (change branch or send sms)
    if request.method == 'POST':
        action_type = request.POST.get('action_type', '')
        customer_id = request.POST.get('customer_id', '')

        if not customer_id:
            messages.error(request, "No customer specified.")
            return redirect('manage_customers')

        customer = get_object_or_404(Customer, id=customer_id)

        if action_type == 'change_branch':
            new_branch_id = request.POST.get('new_branch_id', '')
            if new_branch_id:
                new_branch = get_object_or_404(Branch, id=new_branch_id)
                customer.branch = new_branch
                customer.save()
                messages.success(request, f"{customer.user.get_full_name()} was reassigned to {new_branch.name}.")
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
                        messages.error(request, f"Failed to send SMS: {str(e)}")
                else:
                    messages.error(request, "SMS message is empty.")

        # After handling the action, redirect back
        return redirect('manage_customers')

    context = {
        'customers': customers_qs.order_by('user__first_name'),
        'branches': branches,
        'selected_branch_id': branch_id
    }
    return render(request, 'layouts/admin/manage_customers.html', context)


@staff_member_required
def customer_detail_admin(request, customer_id):
    """
    Admin view to see details of a specific customer, including vehicles and service orders.
    """
    customer = get_object_or_404(Customer, id=customer_id)
    vehicles = CustomerVehicle.objects.filter(customer=customer)
    service_orders = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')

    context = {
        'customer': customer,
        'vehicles': vehicles,
        'service_orders': service_orders,
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


@staff_member_required
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


@staff_member_required
def commissions_by_date(request):
    """
    Page where admin can pick a single date (and optionally a branch and worker)
    to see each worker’s total commission for that date.
    Clicking on the total commission shows a breakdown (via AJAX).
    """
    branches = Branch.objects.all()

    selected_branch_id = request.GET.get('branch', '')
    selected_worker_id = request.GET.get('worker', '')  # new worker filter
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

    # Base queryset: commissions for the selected date
    commissions_qs = Commission.objects.filter(date=selected_date)

    # If a branch is selected
    if selected_branch_id:
        commissions_qs = commissions_qs.filter(worker__branch_id=selected_branch_id)

    # If a worker is selected
    if selected_worker_id:
        commissions_qs = commissions_qs.filter(worker_id=selected_worker_id)

    # Group by worker => sum of commissions
    commissions_by_worker = (
        commissions_qs
        .values('worker')
        .annotate(total_commission=Sum('amount'))
        .order_by('-total_commission')
    )

    # Convert to a list of dicts with worker objects
    results = []
    for row in commissions_by_worker:
        worker_id = row['worker']
        worker_obj = Worker.objects.get(id=worker_id)
        results.append({
            'worker': worker_obj,
            'total_commission': row['total_commission']
        })

    # If a branch is selected, we only show workers from that branch in the worker dropdown
    if selected_branch_id:
        possible_workers = Worker.objects.filter(branch_id=selected_branch_id)
    else:
        possible_workers = Worker.objects.all()

    context = {
        'branches': branches,
        'selected_branch_id': selected_branch_id,
        'workers': possible_workers,
        'selected_worker_id': selected_worker_id,
        'selected_date': selected_date,
        'commissions': results,  # a list of dicts {worker, total_commission}
    }
    return render(request, 'layouts/commissions_by_date.html', context)


@staff_member_required
def commission_breakdown(request):
    """
    AJAX endpoint to get the breakdown of commissions for a given worker on a given date.
    Expects GET params: worker_id, date (YYYY-MM-DD).
    Returns a JSON list of commissions => service, amount, etc.
    """
    worker_id = request.GET.get('worker_id')
    date_str = request.GET.get('date')

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)

    worker = get_object_or_404(Worker, id=worker_id)

    # We can select_related the service_rendered => then fetch the service
    commissions = Commission.objects.filter(
        worker=worker,
        date=date_obj
    ).select_related('service_rendered__service')

    data = []
    for c in commissions:
        service_name = ''
        if c.service_rendered and c.service_rendered.service:
            service_name = c.service_rendered.service.service_type
        data.append({
            'service': service_name,
            'amount': float(c.amount),
        })

    return JsonResponse({'success': True, 'commissions': data})


@staff_member_required
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

    context = {
        'branches': branches,
        'selected_branch_id': selected_branch_id,
        'selected_date': selected_date,
        'expenses': expenses_qs,
        'total_expenses': total_expenses,
    }
    return render(request, 'layouts/expenses_by_date.html', context)


@staff_member_required
def financial_overview(request):
    """
    A comprehensive financial overview that supports filtering by:
    - Date range,
    - Month & year,
    - or Week.
    Displays:
      - Total Revenue, Expenses, Commissions, Arrears
      - Daily breakdown in a small multi-line chart
      - Optionally filter by Branch
    """

    branches = Branch.objects.all()
    selected_branch_id = request.GET.get('branch', '')
    view_type = request.GET.get('view_type', 'date_range')  # can be: 'date_range', 'month_year', or 'week'

    # For date range
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    # For month_year
    month_str = request.GET.get('month', '')
    year_str = request.GET.get('year', '')

    # For week
    week_str = request.GET.get('week', '')

    today = timezone.now().date()
    start_date = today
    end_date = today

    # ------------------ Determine final start_date and end_date ------------------
    if view_type == 'month_year':
        try:
            month = int(month_str)
            year = int(year_str)
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
        except (ValueError, TypeError):
            messages.error(request, "Invalid month/year; defaulting to current month.")
            start_date = today.replace(day=1)
            end_date = today

    elif view_type == 'week':
        try:
            week = int(week_str)
            first_day_of_year = datetime(today.year, 1, 1).date()
            first_monday = first_day_of_year
            while first_monday.isoweekday() != 1:
                first_monday += timedelta(days=1)
            start_date = first_monday + timedelta(weeks=week - 1)
            end_date = start_date + timedelta(days=6)
        except (ValueError, TypeError):
            messages.error(request, "Invalid week number; defaulting to current week.")
            today_weekday = today.isoweekday()
            start_date = today - timedelta(days=today_weekday - 1)
            end_date = start_date + timedelta(days=6)

    else:
        # date_range
        try:
            if start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                start_date = today
                end_date = today
        except ValueError:
            messages.error(request, "Invalid date range; showing today's data.")
            start_date = today
            end_date = today

    if start_date > end_date:
        messages.warning(request, "Start date was after end date. Swapping them.")
        start_date, end_date = end_date, start_date

    # ------------------ Query Sums in the date range ------------------
    revenue_qs = Revenue.objects.filter(date__range=[start_date, end_date])
    expense_qs = Expense.objects.filter(date__range=[start_date, end_date])
    commission_qs = Commission.objects.filter(date__range=[start_date, end_date])
    arrears_qs = Arrears.objects.filter(date_created__date__gte=start_date, date_created__date__lte=end_date)

    # Filter by branch if selected
    if selected_branch_id:
        revenue_qs = revenue_qs.filter(branch_id=selected_branch_id)
        expense_qs = expense_qs.filter(branch_id=selected_branch_id)
        commission_qs = commission_qs.filter(worker__branch_id=selected_branch_id)
        arrears_qs = arrears_qs.filter(branch_id=selected_branch_id)

    total_revenue = revenue_qs.aggregate(total=Sum('final_amount'))['total'] or 0
    total_expenses = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_commissions = commission_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_arrears = arrears_qs.aggregate(total=Sum('amount_owed'))['total'] or 0

    # ------------------ Build daily data for chart ------------------
    daily_data = {}
    cur_date = start_date
    while cur_date <= end_date:
        daily_data[cur_date] = {
            'revenue': 0.0,
            'expense': 0.0,
            'commission': 0.0,
            'arrears': 0.0,
            'net': 0.0,
        }
        cur_date += timedelta(days=1)

    # Summarize daily revenues
    for rev in revenue_qs.values('date').annotate(sum_rev=Sum('final_amount')):
        day = rev['date']
        if day in daily_data:
            daily_data[day]['revenue'] = float(rev['sum_rev'] or 0)

    # Summarize daily expenses
    for exp in expense_qs.values('date').annotate(sum_exp=Sum('amount')):
        day = exp['date']
        if day in daily_data:
            daily_data[day]['expense'] = float(exp['sum_exp'] or 0)

    # Summarize daily commissions
    for com in commission_qs.values('date').annotate(sum_com=Sum('amount')):
        day = com['date']
        if day in daily_data:
            daily_data[day]['commission'] = float(com['sum_com'] or 0)

    # Summarize daily arrears by creation date
    for arr in arrears_qs:
        arr_day = arr.date_created.date()
        if arr_day in daily_data:
            daily_data[arr_day]['arrears'] += float(arr.amount_owed or 0)

    # Compute net
    for d, vals in daily_data.items():
        vals['net'] = vals['revenue'] - vals['expense']

    # Sort by day
    sorted_days = sorted(daily_data.keys())
    chart_labels = [d.strftime('%Y-%m-%d') for d in sorted_days]
    chart_revenues = [daily_data[d]['revenue'] for d in sorted_days]
    chart_expenses = [daily_data[d]['expense'] for d in sorted_days]
    chart_commissions = [daily_data[d]['commission'] for d in sorted_days]
    chart_arrears = [daily_data[d]['arrears'] for d in sorted_days]
    chart_nets = [daily_data[d]['net'] for d in sorted_days]

    # Prepare daily_data_list for table
    daily_data_list = []
    for d in sorted_days:
        daily_data_list.append({
            'date': d.strftime('%Y-%m-%d'),
            'revenue': daily_data[d]['revenue'],
            'expense': daily_data[d]['expense'],
            'net': daily_data[d]['net'],
        })

    # Prepare months list
    months = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    ]

    # Dump chart data as JSON
    import json
    chart_labels_json = json.dumps(chart_labels)
    chart_revenues_json = json.dumps(chart_revenues)
    chart_expenses_json = json.dumps(chart_expenses)
    chart_commissions_json = json.dumps(chart_commissions)
    chart_arrears_json = json.dumps(chart_arrears)
    chart_nets_json = json.dumps(chart_nets)

    context = {
        'branches': branches,
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
        'months': months,

        # JSON data for chart
        'chart_labels_json': chart_labels_json,
        'chart_revenues_json': chart_revenues_json,
        'chart_expenses_json': chart_expenses_json,
        'chart_commissions_json': chart_commissions_json,
        'chart_arrears_json': chart_arrears_json,
        'chart_nets_json': chart_nets_json,
    }

    return render(request, 'layouts/financial_overview.html', context)


from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from django.db.models import Sum, F
from datetime import datetime, date
from django.contrib import messages

from .models import Branch, ProductSale, ProductCategory

@staff_member_required
def product_sales_report(request):
    """
    Shows a product sales report with filters for date/month/year,
    plus branch & category filters. Displays profit and a category
    breakdown chart.
    """
    branches = Branch.objects.all()
    categories = ProductCategory.objects.all()

    # 1) Capture filters from GET
    branch_id = request.GET.get('branch', '')
    category_id = request.GET.get('category', '')
    date_str = request.GET.get('date', '')       # e.g. 2025-02-20
    month_str = request.GET.get('month', '')     # e.g. "02"
    year_str = request.GET.get('year', '')       # e.g. "2025"

    # We'll build our queryset step by step
    sales_qs = ProductSale.objects.all()

    # 2) Apply Branch filter if any
    if branch_id:
        sales_qs = sales_qs.filter(branch_id=branch_id)

    # 3) Apply Category filter if any
    #    ProductSale has product__category
    if category_id:
        sales_qs = sales_qs.filter(product__category_id=category_id)

    # 4) Date vs. Month-Year vs. Year
    #    If "date" is given, we ignore month/year filters
    selected_date = None
    selected_month = None
    selected_year = None

    try:
        # (a) Exact date takes precedence if provided
        if date_str:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            sales_qs = sales_qs.filter(date_sold__date=selected_date)

        # (b) Else if month & year are provided
        elif month_str and year_str:
            selected_month = int(month_str)
            selected_year = int(year_str)
            # Filter by year + month
            sales_qs = sales_qs.filter(
                date_sold__year=selected_year,
                date_sold__month=selected_month
            )

        # (c) Else if only year is provided
        elif year_str:
            selected_year = int(year_str)
            sales_qs = sales_qs.filter(date_sold__year=selected_year)

        # (d) If none provided, default to "today" or entire range
        else:
            # For demonstration: default to "today"
            selected_date = timezone.now().date()
            sales_qs = sales_qs.filter(date_sold__date=selected_date)

    except ValueError:
        messages.error(request, "Invalid date/month/year format. Showing today's data.")
        selected_date = timezone.now().date()
        sales_qs = sales_qs.filter(date_sold__date=selected_date)

    # 5) Calculate aggregates
    #    total_revenue = sum of total_price
    #    total_cost = sum of (product.cost * quantity)
    #    total_profit = sum of ( (product.price - product.cost) * quantity )
    # We can do that with annotations or just sum manually:
    sales_qs = sales_qs.annotate(
        line_cost=F('product__cost') * F('quantity'),
        line_profit=(F('product__price') - F('product__cost')) * F('quantity')
    )

    total_revenue = sales_qs.aggregate(sum_rev=Sum('total_price'))['sum_rev'] or 0
    total_cost = sales_qs.aggregate(sum_cost=Sum('line_cost'))['sum_cost'] or 0
    total_profit = sales_qs.aggregate(sum_profit=Sum('line_profit'))['sum_profit'] or 0

    # 6) Category breakdown for Chart.js
    #    sum by product__category
    #    We'll store labels & data in arrays
    cat_data_qs = sales_qs.values('product__category__name').annotate(
        cat_revenue=Sum('total_price'),
        cat_profit=Sum('line_profit')
    )
    # Build arrays for chart
    chart_labels = []
    chart_revenue_data = []
    chart_profit_data = []

    for row in cat_data_qs:
        cat_name = row['product__category__name'] or "Uncategorized"
        chart_labels.append(cat_name)
        chart_revenue_data.append(float(row['cat_revenue'] or 0))
        chart_profit_data.append(float(row['cat_profit'] or 0))

    months = [f"{i:02d}" for i in range(1, 13)]

    stock_summary_qs = Product.objects.values('category__name').annotate(
        in_stock_qty=Sum('stock'),
        total_cost_if_sold=Sum(F('stock') * F('cost')),
        total_price_if_sold=Sum(F('stock') * F('price')),
        total_profit_if_sold=Sum((F('price') - F('cost')) * F('stock'))
    ).order_by('category__name')

    # Convert to a list of dicts for easy looping in template
    # You might store category_id as well if you want links.
    stock_summary = []
    for row in stock_summary_qs:
        cat_name = row['category__name'] or "Uncategorized"
        stock_summary.append({
            'category_name': cat_name,
            'in_stock_qty': row['in_stock_qty'] or 0,
            'total_cost_if_sold': row['total_cost_if_sold'] or 0.0,
            'total_price_if_sold': row['total_price_if_sold'] or 0.0,
            'total_profit_if_sold': row['total_profit_if_sold'] or 0.0,
        })

    # 7) Prepare context
    context = {
        'branches': branches,
        'categories': categories,
        'months': months,

        'selected_branch_id': branch_id,
        'selected_category_id': category_id,

        'date_str': date_str,
        'month_str': month_str,
        'year_str': year_str,
        'selected_date': selected_date,
        'selected_month': selected_month,
        'selected_year': selected_year,

        'sales': sales_qs,  # includes line_cost & line_profit annotations
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_profit': total_profit,

        # Chart data
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

    # Send an SMS to the customer, if a phone number is available
    service_order = arrears.service_order
    service_order.status = "completed"
    service_order.save()
    if service_order and service_order.customer and service_order.customer.user.phone_number:
        phone_number = service_order.customer.user.phone_number
        # Customize your message text as needed
        message_text = (
            f"Hello {service_order.customer.user.first_name}, "
            f"your on-credit service (Order #{service_order.service_order_number}) for {arrears.date_created}"
            f"with an amount of GHS {arrears.amount_owed:.2f} has now been fully paid. "
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


@login_required(login_url='login')
def worker_commissions(request):
    """
    Worker view: shows a chart and table of daily commissions over the last N days.
    N is chosen by a dropdown or query param, default 7.
    Each day row lists the combined services and the daily total.
    """
    user = request.user
    try:
        worker = get_object_or_404(Worker, user=user)
    except Worker.DoesNotExist:
        messages.error(request, "You are not authorized to view commissions.")
        return redirect('index')

    # Number of days to look back (default 7). We allow 'days' param in GET: ?days=7 or ?days=15
    days_str = request.GET.get('days', '7')
    try:
        days = int(days_str)
    except ValueError:
        days = 7
    if days <= 0:
        days = 7  # fallback

    today = date.today()
    start_date = today - timedelta(days=days - 1)  # last N days, inclusive
    # We'll gather commissions from start_date to today (inclusive)

    # Filter Commission by date range
    commissions_qs = Commission.objects.filter(
        worker=worker,
        date__range=[start_date, today]
    ).select_related('service_rendered__service')  # so we can get service name easily

    # We'll group by day => store list of service names & sum of amounts
    # Build a dictionary day => { 'services': set(), 'total': 0.0 }
    daily_data = {}
    # Initialize for each day so we have a row even if it's 0 commission
    current = start_date
    while current <= today:
        daily_data[current] = {
            'services': set(),
            'total': 0.0
        }
        current += timedelta(days=1)

    # Populate from commissions
    for c in commissions_qs:
        day = c.date
        if day in daily_data:
            # Add service name if any
            service_name = ''
            if c.service_rendered and c.service_rendered.service:
                service_name = c.service_rendered.service.service_type
            if service_name:
                daily_data[day]['services'].add(service_name)
            # sum
            daily_data[day]['total'] += float(c.amount or 0)

    # Sort by day for displaying
    sorted_days = sorted(daily_data.keys())

    # Build data for the chart
    chart_labels = []
    chart_values = []
    daily_rows = []
    for d in sorted_days:
        chart_labels.append(d.strftime('%Y-%m-%d'))
        chart_values.append(daily_data[d]['total'])

        # Convert the set of services to a comma list
        service_list_str = ', '.join(sorted(daily_data[d]['services']))
        daily_rows.append({
            'date': d,
            'services': service_list_str if service_list_str else '---',
            'total': daily_data[d]['total']
        })

    # Convert chart data to JSON for Chart.js
    chart_labels_json = json.dumps(chart_labels)
    chart_values_json = json.dumps(chart_values)

    context = {
        'worker': worker,
        'days': days,
        'daily_rows': daily_rows,
        'chart_labels_json': chart_labels_json,
        'chart_values_json': chart_values_json,
    }
    return render(request, 'layouts/workers/my_commissions.html', context)


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
    assign them to a branch, optionally set gh_card_number, gh_card_photo, etc.,
    and email them a password reset link to set their password.
    """
    if request.method == 'POST':
        form = EnrollWorkerForm(request.POST, request.FILES)  # include request.FILES for image upload
        if form.is_valid():
            with transaction.atomic():
                # Extract data
                first_name = form.cleaned_data['first_name']
                last_name = form.cleaned_data['last_name']
                email = form.cleaned_data['email']
                phone_number = form.cleaned_data['phone_number']
                branch = form.cleaned_data['branch']
                position = form.cleaned_data['position']
                salary = form.cleaned_data.get('salary') or 0.0
                gh_card_number = form.cleaned_data['gh_card_number']
                year_of_admission = form.cleaned_data.get('year_of_admission') or None
                is_branch_head = form.cleaned_data.get('is_branch_head', False)

                # Check if phone already exists
                if CustomUser.objects.filter(phone_number=phone_number).exists():
                    form.add_error('phone_number', 'This phone number is already in use.')
                    return render(request, 'layouts/admin/enroll_worker.html', {'form': form})

                # Create CustomUser (role=worker)
                user = CustomUser.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone_number=phone_number,
                    username=phone_number,
                    role='worker',
                    is_active=True,  # so they can reset password
                )
                # Create Worker profile
                worker = Worker.objects.create(
                    user=user,
                    branch=branch,
                    position=position,
                    salary=salary,
                    gh_card_number=gh_card_number,
                    year_of_admission=year_of_admission,
                    is_branch_head=is_branch_head
                )

                # Generate password reset link
                from django.contrib.sites.shortcuts import get_current_site
                current_site = get_current_site(request)
                domain = current_site.domain
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = reverse('password_reset_confirm', kwargs={
                    'uidb64': uid,
                    'token': token,
                })
                reset_link = f"http://{domain}{reset_url}"

                # Email the link to the user
                subject = "Welcome to AutoDash - Set Your Password"
                message = (
                    f"Hello {first_name},\n\n"
                    f"You have been enrolled as a worker at {branch.name}.\n"
                    f"Please set your password using the link below:\n\n"
                    f"{reset_link}\n\n"
                    f"Thank you!"
                )
                print(message)
            if phone_number:
                try:
                    send_sms(phone_number, message)
                except Exception as e:
                    print(e)
            # if email:
            #     send_mail(
            #         subject,
            #         message,
            #         settings.DEFAULT_FROM_EMAIL,
            #         [email],
            #         fail_silently=False,
            #     )

            messages.success(request,
                             "Worker enrolled successfully. Password reset link sent (if phone number provided).")
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
            phone_number = customer.user.phone_number
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

                # Example: for each branch, gather stats in a list or dictionary
                branch_data = []
                for br in branches_qs:
                    # Revenue in range
                    rev_total = Revenue.objects.filter(
                        branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('final_amount'))['total'] or 0

                    # Expense
                    exp_total = Expense.objects.filter(
                        branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    # Commission
                    comm_total = Commission.objects.filter(
                        worker__branch=br,
                        date__range=[final_start, final_end]
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    # Net profit
                    profit = rev_total - exp_total

                    # Workers & customers
                    worker_count = Worker.objects.filter(branch=br).count()
                    customer_count = Customer.objects.filter(branch=br).count()  # if you store branch in Customer
                    # Alternatively, if you do not store branch in Customer model,
                    # you can find how many used that branch in orders, etc.

                    branch_data.append({
                        'branch': br,
                        'revenue': rev_total,
                        'expense': exp_total,
                        'commission': comm_total,
                        'profit': profit,
                        'workers': worker_count,
                        'customers': customer_count,
                    })

                context['results']['branch_data'] = branch_data

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
