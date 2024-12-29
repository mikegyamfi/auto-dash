import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Sum, Avg, functions, Q
from django.db.models.functions import TruncDate
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import models, helper, forms

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, Avg
from .models import (
    AdminAccount, Expense, Revenue, ServiceRenderedOrder, Worker, ProductPurchased,
    Commission, Branch, DailyExpenseBudget, ServiceRendered
)


@login_required(login_url='login')
def home(request):
    user = request.user
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    if user.is_staff or user.is_superuser:
        # Admin View

        # Check if branch is selected
        branch_id = request.GET.get('branch_id')

        if branch_id:
            # Branch is selected, proceed to generate dashboard
            try:
                branch = Branch.objects.get(id=branch_id)
            except Branch.DoesNotExist:
                messages.error(request, 'Selected branch does not exist.')
                return redirect('home')  # Redirect back to branch selection

            # Get number of days for worker statistics
            days = request.GET.get('days', '10')  # Default to past 10 days
            try:
                days = int(days)
                if days <= 0:
                    days = 10
            except (ValueError, TypeError):
                days = 10

            # Get start and end days ago for expenses
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
            except (ValueError, TypeError):
                start_days_ago = 20
                end_days_ago = 10

            # Calculate date ranges
            start_date = today - timedelta(days=days)
            expense_start_date = today - timedelta(days=start_days_ago)
            expense_end_date = today - timedelta(days=end_days_ago)

            # Total expenses today
            expenses_today = Expense.objects.filter(branch=branch, date=today).aggregate(total=Sum('amount'))['total'] or 0

            # Daily expense budget
            daily_budget = DailyExpenseBudget.objects.filter(branch=branch, date=today).first()
            daily_expense_budget = daily_budget.budgeted_amount if daily_budget else 0

            expenses_over_budget = expenses_today > daily_expense_budget

            # Calculate budget difference
            budget_difference = abs(expenses_today - daily_expense_budget)

            # Total revenue today
            revenue_today = Revenue.objects.filter(branch=branch, date=today).aggregate(total=Sum('final_amount'))['total'] or 0
            revenue_yesterday = Revenue.objects.filter(branch=branch, date=yesterday).aggregate(total=Sum('final_amount'))['total'] or 0

            # Calculate profit
            profit_today = revenue_today - expenses_today

            # Percentage increase in revenue
            if revenue_yesterday > 0:
                percentage_increase = ((revenue_today - revenue_yesterday) / revenue_yesterday) * 100
            else:
                percentage_increase = 0
            percentage_increase = round(percentage_increase, 2)

            # Services rendered today
            services_rendered_today = ServiceRenderedOrder.objects.filter(
                branch=branch, date__date=today, status='completed'
            ).count()
            services_rendered_yesterday = ServiceRenderedOrder.objects.filter(
                branch=branch, date__date=yesterday, status='completed'
            ).count()

            if services_rendered_yesterday > 0:
                services_percentage_change = ((services_rendered_today - services_rendered_yesterday) / services_rendered_yesterday) * 100
            else:
                services_percentage_change = 0
            services_percentage_change = round(services_percentage_change, 2)

            # Total commission today
            total_commission = Commission.objects.filter(worker__branch=branch, date=today).aggregate(total=Sum('amount'))['total'] or 0

            # Products sold today
            products_sold_today = ProductPurchased.objects.filter(
                service_order__branch=branch, service_order__date__date=today
            ).aggregate(total=Sum('quantity'))['total'] or 0

            # Recent services
            recent_services = ServiceRenderedOrder.objects.filter(branch=branch).order_by('-date')[:5]

            # Pending services
            pending_services = ServiceRenderedOrder.objects.filter(branch=branch, status='pending').order_by('-date')

            # Completed and pending orders
            completed_orders = ServiceRenderedOrder.objects.filter(branch=branch, status='completed').count()
            on_credit_orders = ServiceRenderedOrder.objects.filter(branch=branch, status='onCredit').count()
            pending_orders_today = ServiceRenderedOrder.objects.filter(branch=branch, status='pending', date__date=today).count()

            # Add counts of orders under each status
            total_orders = ServiceRenderedOrder.objects.filter(branch=branch).count()
            completed_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='completed').count()
            pending_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='pending').count()
            canceled_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='canceled').count()
            on_credit_orders_count = ServiceRenderedOrder.objects.filter(branch=branch, status='onCredit').count()

            # Services by each worker in the past N days
            workers = Worker.objects.filter(branch=branch)

            services_by_worker = workers.annotate(
                total_services=Count(
                    'servicerenderedorder',
                    filter=Q(servicerenderedorder__date__gte=start_date, servicerenderedorder__status='completed')
                )
            ).order_by('-total_services')

            # Commission by worker in the past N days
            commission_by_worker = workers.annotate(
                total_commission=Sum(
                    'commissions__amount',
                    filter=Q(commissions__date__gte=start_date)
                )
            ).order_by('-total_commission')

            # Expenses of the branch from expense_start_date to expense_end_date
            expenses_in_range = Expense.objects.filter(
                branch=branch,
                date__range=[expense_end_date, expense_start_date]
            ).order_by('-date')

            # Total expenses in the range
            total_expenses_in_range = expenses_in_range.aggregate(total=Sum('amount'))['total'] or 0

            # Define options for days selection
            days_options = [5, 10, 15, 30, 60, 90]

            context = {
                'is_admin': True,
                'branch': branch,
                'expenses_today': expenses_today,
                'daily_expense_budget': daily_expense_budget,
                'expenses_over_budget': expenses_over_budget,
                'budget_difference': budget_difference,
                'revenue_today': revenue_today,
                'profit_today': profit_today,
                'percentage_increase': percentage_increase,
                'services_rendered_today': services_rendered_today,
                'services_percentage_change': services_percentage_change,
                'total_commission': total_commission,
                'products_sold_today': products_sold_today,
                'recent_services': recent_services,
                'pending_services': pending_services,
                'completed_orders': completed_orders,
                'on_credit_orders': on_credit_orders,
                'pending_orders_today': pending_orders_today,
                'services_by_worker': services_by_worker,
                'commission_by_worker': commission_by_worker,
                'days': days,
                'start_days_ago': start_days_ago,
                'end_days_ago': end_days_ago,
                'expenses_in_range': expenses_in_range,
                'total_expenses_in_range': total_expenses_in_range,
                'days_options': days_options,
                'total_orders': total_orders,
                'completed_orders_count': completed_orders_count,
                'pending_orders_count': pending_orders_count,
                'canceled_orders_count': canceled_orders_count,
                'on_credit_orders_count': on_credit_orders_count,
            }

            return render(request, 'layouts/admin/dashboard.html', context)

        else:
            # Branch not selected, display branch selection page
            branches = Branch.objects.all()
            context = {'branches': branches}
            return render(request, 'layouts/admin/select_branch.html', context)

    else:
        # Worker View
        try:
            worker = Worker.objects.get(user=user)
            branch = worker.branch
        except Worker.DoesNotExist:
            # Handle the case where the user is not associated with a worker profile
            messages.error(request, 'Your account is not properly configured.')
            return redirect('logout')

        # Commission earned by the worker today
        worker_commission_today = Commission.objects.filter(worker=worker, date=today).aggregate(
            total=Sum('amount')
        )['total'] or 0

        # Services rendered by the worker today
        services_rendered_today = ServiceRenderedOrder.objects.filter(
            workers=worker, date__date=today
        ).count()

        # Recent services performed by the worker
        recent_services = ServiceRenderedOrder.objects.filter(
            workers=worker
        ).distinct().order_by('-date')[:5]

        # Pending services assigned to the worker
        pending_services = ServiceRenderedOrder.objects.filter(
            status='pending', workers=worker
        ).distinct().order_by('-date')

        # Completed orders by the worker
        completed_orders = ServiceRenderedOrder.objects.filter(
            status='completed', workers=worker
        ).distinct().count()

        # On credit orders handled by the worker
        on_credit_orders = ServiceRenderedOrder.objects.filter(
            status='onCredit', workers=worker
        ).distinct().count()

        # Average rating (assuming you have a method to calculate this)
        average_rating = worker.average_rating()  # Implement this method in your Worker model

        # Total services count
        services_count = ServiceRenderedOrder.objects.filter(workers=worker).count()

        context = {
            'is_admin': False,
            'worker': worker,
            'branch': branch,
            'worker_commission_today': worker_commission_today,
            'services_rendered_today': services_rendered_today,
            'recent_services': recent_services,
            'pending_services': pending_services,
            'completed_orders': completed_orders,
            'on_credit_orders': on_credit_orders,
            'average_rating': average_rating,
            'services_count': services_count,
        }

        return render(request, 'layouts/index.html', context)


# def service(request):
#     return render(request, "layouts/service.html")


from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from .models import Customer, Worker, Service, ServiceRendered, Subscription, CustomerSubscription, CustomUser, \
    ServiceRenderedOrder, Revenue, Branch, Expense, DailyExpenseBudget, Commission, ProductPurchased
from .forms import LogServiceForm, NewCustomerForm, BranchForm, ExpenseForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.template.loader import render_to_string


@login_required(login_url='login')
@transaction.atomic
def log_service(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    worker = models.Worker.objects.get(user=user)

    if user.role == "worker" or user.role == "Admin":
        if request.method == 'POST':
            form = LogServiceForm(data=request.POST, branch=worker.branch)
            if form.is_valid():
                # Get form data
                customer = form.cleaned_data['customer']
                vehicle = form.cleaned_data['vehicle']
                selected_services = form.cleaned_data['service']
                selected_workers = form.cleaned_data['workers']
                selected_products = form.cleaned_data.get('products', [])
                product_quantities = request.POST.getlist('product_quantity')  # Assuming quantities are sent as a list

                # Calculate total amount for services
                total_services = sum([float(service.price) for service in selected_services])

                # Calculate total amount for products
                total_products = 0
                products_purchased = []
                for product, qty in zip(selected_products, product_quantities):
                    quantity = int(qty) if qty.isdigit() else 1
                    if product.stock < quantity:
                        messages.error(request, f'Not enough stock for {product.name}. Available: {product.stock}')
                        return redirect('log_service')
                    total_products += product.price * quantity
                    products_purchased.append(
                        {'product': product, 'quantity': quantity, 'total_price': product.price * quantity})

                # Total amount
                total = total_services + total_products

                # Generate unique order number
                order_number = helper.generate_service_order_number(prefix=worker.branch.name[:3])

                # Create new ServiceRenderedOrder
                new_order = models.ServiceRenderedOrder.objects.create(
                    service_order_number=order_number,
                    customer=customer,
                    user=user,
                    total_amount=total,
                    final_amount=total,  # Initial final_amount equals total
                    vehicle=vehicle,
                    branch=worker.branch
                )
                new_order.workers.set(selected_workers)

                # Create ServiceRendered for each selected service
                for service in selected_services:
                    models.ServiceRendered.objects.create(
                        service=service,
                        order=new_order,
                    )

                # Handle Product Purchases
                for item in products_purchased:
                    product = item['product']
                    quantity = item['quantity']
                    total_price = item['total_price']
                    models.ProductPurchased.objects.create(
                        service_order=new_order,
                        product=product,
                        quantity=quantity,
                        total_price=total_price
                    )
                    # Update product stock
                    product.stock -= quantity
                    product.save()

                # Calculate Revenue
                revenue = models.Revenue.objects.create(
                    user=user,
                    amount=total,
                    branch=worker.branch,
                    service_rendered=new_order,
                    final_amount=total  # Initially, final_amount equals total
                )
                revenue.save()

                messages.success(request, 'Service and products logged successfully.')
                return redirect('confirm_service_rendered', pk=new_order.pk)
            else:
                messages.error(request, "Form is invalid. Please correct the errors below.")
                print(form.errors)
        else:
            form = LogServiceForm(branch=worker.branch)

        # Fetch vehicle groups and products to pass to the template
        vehicle_groups = models.VehicleGroup.objects.all()
        products = models.Product.objects.filter(branch=worker.branch)

        return render(request, 'layouts/workers/log_service.html', {
            'form': form,
            'vehicle_groups': vehicle_groups,
            'products': products,  # Pass products to the template
        })
    else:
        messages.info(request, 'You are not allowed to access this page.')
        return redirect('index')


# @receiver(post_save, sender=ServiceRenderedOrder)
# def send_sms_notification(sender, instance, created, **kwargs):
#     services = models.ServiceRendered.objects.filter(order=instance)
#     if created:
#         customer_phone = instance.customer.phone_number
#         feedback_url = f"http://localhost:8000/feedback/{instance.id}"
#         message = f"Thank you for your order {instance.service_order_number}. Please provide your feedback: {feedback_url}"
#
#         # Twilio SMS Sending
#         # client = Client("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN")
#         # client.messages.create(
#         #     to=customer_phone,
#         #     from_="YOUR_TWILIO_PHONE_NUMBER",
#         #     body=message
#         # )


@login_required(login_url='login')
def get_customer_vehicles(request, customer_id):
    customer = get_object_or_404(models.Customer, id=customer_id)
    vehicles = models.CustomerVehicle.objects.filter(customer=customer)
    vehicle_list = []
    for vehicle in vehicles:
        vehicle_list.append({
            'id': vehicle.id,
            'display': f"{vehicle.vehicle_group.group_name} - {vehicle.car_make} {vehicle.car_plate} ({vehicle.car_color})",
        })
    return JsonResponse({'vehicles': vehicle_list})


@login_required(login_url='login')
def create_vehicle(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        customer = get_object_or_404(models.Customer, id=customer_id)
        vehicle_group = get_object_or_404(models.VehicleGroup, id=vehicle_group_id)

        # Create new vehicle
        vehicle = models.CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=vehicle_group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color,
        )

        # Return success response
        vehicle_data = {
            'id': vehicle.id,
            'display': f"{vehicle.car_make} {vehicle.car_plate} ({vehicle.car_color})",
        }
        return JsonResponse({'success': True, 'vehicle': vehicle_data})
    else:
        return JsonResponse({'success': False})


@login_required(login_url='login')
def add_vehicle_to_customer(request, customer_id):
    if request.method == 'POST':
        # Get the customer
        customer = get_object_or_404(models.Customer, id=customer_id)

        # Get form data
        vehicle_group_id = request.POST.get('vehicle_group')
        car_make = request.POST.get('car_make')
        car_plate = request.POST.get('car_plate')
        car_color = request.POST.get('car_color')

        # Validate data
        if not all([vehicle_group_id, car_make, car_plate, car_color]):
            return JsonResponse({'success': False, 'message': 'All fields are required.'})

        # Get the vehicle group
        vehicle_group = get_object_or_404(models.VehicleGroup, id=vehicle_group_id)

        # Create the vehicle
        vehicle = models.CustomerVehicle.objects.create(
            customer=customer,
            vehicle_group=vehicle_group,
            car_make=car_make,
            car_plate=car_plate,
            car_color=car_color,
        )

        # Return success response with vehicle data
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

    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required(login_url='login')
def get_vehicle_services(request, vehicle_id):
    vehicle = get_object_or_404(models.CustomerVehicle, id=vehicle_id)
    vehicle_group = vehicle.vehicle_group
    services = models.Service.objects.filter(vehicle_group=vehicle_group, active=True)
    service_list = []
    for service in services:
        service_list.append({
            'id': service.id,
            'name': f"{service.service_type}-{service.vehicle_group}",
        })
    return JsonResponse({'services': service_list})


def service_feedback_page(request, pk):
    service_order = models.ServiceRenderedOrder.objects.get(id=pk)
    services_under_service_order = models.ServiceRendered.objects.filter(order=service_order)

    # Check if feedback and rating have already been provided
    if service_order.customer_feedback and service_order.customer_rating:
        messages.success(request, 'Your feedback has been recorded.')

    if request.method == 'POST':
        rating = request.POST.get('rating')
        feedback = request.POST['feedback']

        print(rating)
        print(feedback)

        service_order.customer_rating = rating
        service_order.customer_feedback = feedback
        service_order.save()

        # Update the workers' ratings
        workers = service_order.workers.all()
        for worker in workers:
            worker.add_rating(int(rating))
            worker.save()

        # Optionally, redirect to a thank you page after submission
        messages.success(request, 'Your feedback has been recorded.')
        return redirect('thank_you_for_feedback', pk=service_order.id)

    return render(request, "layouts/service_feedback_page.html",
                  {'service_order': service_order, 'services': services_under_service_order})


def thank_you_feedback(request, pk):
    service_order = models.ServiceRenderedOrder.objects.get(id=pk)
    stars_given = service_order.customer_rating
    return render(request, 'layouts/thank_you_for_feedback.html',
                  context={'service_order': service_order, 'stars_given': stars_given})


@login_required(login_url='login')
def confirm_service(request, pk):
    user = models.CustomUser.objects.get(id=request.user.id)
    worker = models.Worker.objects.get(user=user)
    service_order = get_object_or_404(models.ServiceRenderedOrder, pk=pk)
    services_rendered = models.ServiceRendered.objects.filter(order=service_order)
    customer = service_order.customer

    # Initialize total_amount as the sum of all service and product prices
    total_service_amount = sum([service_rendered.service.price for service_rendered in services_rendered])
    total_product_amount = sum([product_purchased.total_price for product_purchased in service_order.products_purchased.all()])
    total_amount = total_service_amount + total_product_amount
    final_amount = total_amount  # Start with total_amount

    if request.method == 'GET':
        loyalty_points = customer.loyalty_points

        # Handle Subscription
        try:
            customer_subscription = models.CustomerSubscription.objects.get(customer=customer)
            if not customer_subscription.is_active():
                active_subscription = False
                customer_subscription = None
            else:
                active_subscription = True
                subscription = customer_subscription.subscription
                subscription_services = subscription.services.all()
                subscription_vehicle_groups = subscription.vehicle_group.all()

                # Adjust final_amount for services covered by subscription
                for service_rendered in services_rendered:
                    service = service_rendered.service
                    vehicle = service_order.vehicle
                    vehicle_group = vehicle.vehicle_group if vehicle else None

                    if service in subscription_services and vehicle_group in subscription_vehicle_groups:
                        final_amount -= service.price

                final_amount = max(final_amount, 0)

        except models.CustomerSubscription.DoesNotExist:
            active_subscription = False
            customer_subscription = None

        # Save the total_amount and final_amount to service_order
        service_order.total_amount = total_amount
        service_order.final_amount = final_amount
        service_order.save()

        # Get available products
        available_products = models.Product.objects.filter(branch=worker.branch)

        context = {
            'service_order': service_order,
            'services': services_rendered,
            'loyalty_points': loyalty_points,
            'active_subscription': active_subscription,
            'subscription': customer_subscription,
            'service_customer': customer,
            'available_products': available_products,
        }
        return render(request, "layouts/workers/confirm_service_order.html", context=context)

    elif request.method == 'POST':
        # Get status from POST data
        status = request.POST.get('status', 'completed')
        service_order.status = status
        payment_method = request.POST.get('payment_method')
        service_order.payment_method = payment_method
        service_order.branch = worker.branch

        # Collect services to redeem with loyalty points
        services_to_redeem = []
        total_loyalty_points_required = 0

        for service_rendered in services_rendered:
            checkbox_name = f'redeem_service_{service_rendered.id}'
            if checkbox_name in request.POST:
                services_to_redeem.append(service_rendered)
                total_loyalty_points_required += service_rendered.service.loyalty_points_required

        # Check if customer has enough loyalty points
        if total_loyalty_points_required > customer.loyalty_points:
            messages.error(request, 'Not enough loyalty points to redeem selected services.')
            return redirect(request.path)

        # Adjust final_amount based on loyalty point redemptions
        final_amount = service_order.final_amount  # After subscription adjustments

        for service_rendered in services_to_redeem:
            final_amount -= service_rendered.service.price
            customer.loyalty_points -= service_rendered.service.loyalty_points_required
            models.LoyaltyTransaction.objects.create(
                customer=customer,
                points=-service_rendered.service.loyalty_points_required,
                transaction_type="redeem",
                description=f'Redeemed for {service_rendered.service.service_type}',
                branch=worker.branch,
            )

        final_amount = max(final_amount, 0)

        # Collect additional products added
        product_ids = [key.split('_')[1] for key in request.POST.keys() if key.startswith('product_')]
        products_purchased = []
        total_products_price = 0

        for product_id in product_ids:
            quantity_str = request.POST.get(f'product_{product_id}')
            quantity = int(quantity_str) if quantity_str and quantity_str.isdigit() else 0
            if quantity > 0:
                product = get_object_or_404(models.Product, id=product_id)
                if product.stock < quantity:
                    messages.error(request, f'Not enough stock for {product.name}. Available: {product.stock}')
                    return redirect(request.path)
                total_price = product.price * quantity
                total_products_price += total_price
                products_purchased.append({'product': product, 'quantity': quantity, 'total_price': total_price})

        # Adjust final_amount and total_amount based on additional products
        service_order.total_amount += total_products_price
        final_amount += total_products_price

        # Create ProductPurchased entries and update product stock
        for item in products_purchased:
            product = item['product']
            quantity = item['quantity']
            total_price = item['total_price']
            models.ProductPurchased.objects.create(
                service_order=service_order,
                product=product,
                quantity=quantity,
                total_price=total_price
            )
            # Update product stock
            product.stock -= quantity
            product.save()

        # Get discount type and value from POST data
        discount_type = request.POST.get('discount_type', 'amount')
        discount_value_str = request.POST.get('discount_value')
        discount_value = float(discount_value_str) if discount_value_str and discount_value_str.strip() != '' else 0.0
        discount_value = max(discount_value, 0)

        # Apply discount
        if discount_type == 'percentage':
            discount_value = min(discount_value, 100)
            discount_amount = (final_amount * discount_value) / 100
        else:
            discount_amount = min(discount_value, final_amount)

        final_amount -= discount_amount
        final_amount = max(final_amount, 0)

        # Save the discount to the service_order
        service_order.discount_type = discount_type
        service_order.discount_value = discount_value
        service_order.final_amount = final_amount
        service_order.save()

        customer.save()

        # Add loyalty points earned for all services
        for service_rendered in services_rendered:
            customer.loyalty_points += service_rendered.service.loyalty_points_earned
            models.LoyaltyTransaction.objects.create(
                customer=customer,
                points=service_rendered.service.loyalty_points_earned,
                transaction_type="gain",
                description=f'Points earned for {service_rendered.service.service_type}',
                branch=worker.branch,
            )

        customer.save()

        # Handle Revenue based on status
        if service_order.status == 'completed':
            revenue, created = models.Revenue.objects.get_or_create(
                service_rendered=service_order,
                defaults={
                    'user': user,
                    'branch': worker.branch,
                    'amount': service_order.total_amount,
                    'final_amount': final_amount,
                    'date': service_order.date.date(),
                }
            )
            if not created:
                revenue.amount = service_order.total_amount
                revenue.final_amount = final_amount
                revenue.save()
        else:
            # If Revenue object exists, delete it
            models.Revenue.objects.filter(service_rendered=service_order).delete()

        messages.success(request, 'Service Log confirmed.')
        return redirect('index')


@login_required(login_url='login')
def discard_order(request, pk):
    order_to_be_discarded = models.ServiceRenderedOrder.objects.get(pk=pk)
    order_to_be_discarded.delete()
    return redirect('index')


def service_order_details(request, pk):
    # Fetch the specific service order by primary key
    service_order = get_object_or_404(ServiceRenderedOrder, pk=pk)

    # Fetch services rendered for this specific order
    services_rendered = ServiceRendered.objects.filter(order=service_order)
    print(services_rendered)

    context = {
        'service_order': service_order,
        'services_rendered': services_rendered,
    }

    return render(request, 'layouts/workers/service_order_details.html', context)


@login_required(login_url='login')
def check_customer_status(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    active_subscriptions = CustomerSubscription.objects.filter(customer=customer, end_date__gte=timezone.now())
    active_subscription = active_subscriptions.exists()
    loyalty_points = customer.loyalty_points
    return JsonResponse({
        'active_subscription': active_subscription,
        'loyalty_points': loyalty_points
    })



@login_required(login_url='login')
def create_customer(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        phone_number = request.POST.get('phone_number')
        if first_name and last_name and phone_number:
            if CustomUser.objects.filter(phone_number=phone_number).exists():
                return JsonResponse({'success': False, 'error': 'Customer with this phone number already exists.'})
            new_custom_user = CustomUser.objects.create(
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                username=phone_number,
                role='customer',
            )
            new_customer = models.Customer.objects.create(user=new_custom_user)
            # Send password reset email to new customer
            # send_password_reset(new_custom_user)
            return JsonResponse({
                'success': True,
                'customer': {
                    'id': new_custom_user.id,
                    'name': f"{new_custom_user.first_name} {new_custom_user.last_name}",
                },
            })
        else:
            return JsonResponse({'success': False, 'error': 'Missing required fields.'})
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


def send_password_reset(user):
    print("got here")
    if user:
        # Generate token and UID for the password reset link
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # Prepare the context for the email
        c = {
            "name": user.first_name,
            "email": user.email,
            "uid": uid,
            "token": token,
            'domain': 'localhost:8000',  # Localhost domain
            'site_name': 'AutoDash',
            'protocol': 'http',  # HTTP protocol since it's running on localhost
        }

        # Render email template
        email_template_name = "password/password_reset_message.txt"
        email_content = render_to_string(email_template_name, c)

        # Send email using Django's send_mail
        send_mail(
            subject="Password Reset Requested",
            message=email_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
            fail_silently=False,
        )

        print(email_content)


@login_required(login_url='login')
def service_history(request):
    user = request.user

    # Check if user is a worker or admin
    if user.role not in ["worker", "Admin"]:
        messages.error(request, "You are not authorized to view this page.")
        return redirect('index')

    # Retrieve all service orders, ordered by date descending
    services_rendered = ServiceRenderedOrder.objects.all().order_by('-date')

    # Get all status choices from the model
    statuses = ServiceRenderedOrder.STATUS_CHOICES

    # Filter by status if provided in GET parameters
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        services_rendered = services_rendered.filter(status=status_filter)

    # Handle bulk status change
    if request.method == 'POST':
        selected_order_ids = request.POST.getlist('selected_orders')
        new_status = request.POST.get('new_status')
        valid_statuses = [choice[0] for choice in ServiceRenderedOrder.STATUS_CHOICES]
        if selected_order_ids and new_status in valid_statuses:
            # Update the status of selected orders
            ServiceRenderedOrder.objects.filter(id__in=selected_order_ids).update(status=new_status)
            messages.success(request, "Selected orders have been updated.")
            return redirect('service_history')
        else:
            messages.error(request, "Please select orders and a valid status to update.")

    context = {
        'services_rendered': services_rendered,
        'statuses': statuses,
        'status_filter': status_filter,
    }
    return render(request, 'layouts/workers/service_history.html', context)


# ============================================================================================================================================================
# ============================================================================================================================================================
# ============================================================================================================================================================
# ============================================================================================================================================================
# ============================================================================================================================================================
# ============================================================================================================================================================
# Customer Views
from django.shortcuts import render, get_object_or_404
from .models import Customer, CustomerSubscription, ServiceRenderedOrder, LoyaltyTransaction


@login_required(login_url='login')
def customer_dashboard(request):
    # Get the current customer
    customer = get_object_or_404(Customer, user=request.user)

    # Get customer services rendered
    services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')[:5]

    # Get the customer's active subscription
    active_subscription = CustomerSubscription.objects.filter(customer=customer, end_date__gte=timezone.now()).first()

    # Get customer's loyalty points and recent loyalty transactions
    loyalty_points = customer.loyalty_points
    loyalty_transactions = LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')[:5]

    vehicles = models.CustomerVehicle.objects.filter(customer=customer)

    context = {
        'customer': customer,
        'services_rendered': services_rendered,
        'active_subscription': active_subscription,
        'loyalty_points': loyalty_points,
        'loyalty_transactions': loyalty_transactions,
        'vehicles': vehicles,
    }

    return render(request, 'layouts/customers/customer_index.html', context)


from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import ServiceRenderedOrder, CustomUser, Customer


@login_required(login_url='login')
def customer_service_history(request):
    user = CustomUser.objects.get(id=request.user.id)

    # Get the customer object based on the logged-in user
    customer = Customer.objects.get(user=user)

    # Fetch all service orders related to the customer
    services_rendered = ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')[:20]

    return render(request, 'layouts/customers/service_history.html', {'services_rendered': services_rendered})


@login_required(login_url='login')
def branch_customers(request):
    user = request.user

    # Get the worker object
    try:
        worker = models.Worker.objects.get(user=user)
    except models.Worker.DoesNotExist:
        # Handle the case where the user is not a worker
        messages.error(request, 'You are not authorized to view this page.')
        return redirect('index')

    # Get the branch associated with the worker
    branch = worker.branch

    # Get all customers who have had services at this branch
    service_orders = models.ServiceRenderedOrder.objects.filter(branch=branch)
    customer_ids = service_orders.values_list('customer__id', flat=True).distinct()
    customers = models.Customer.objects.filter(id__in=customer_ids)

    context = {
        'customers': customers,
    }

    return render(request, 'layouts/workers/branch_customers.html', context)


@login_required(login_url='login')
def customer_detail(request, customer_id):
    user = request.user

    # Get the worker object
    try:
        worker = models.Worker.objects.get(user=user)
    except models.Worker.DoesNotExist:
        messages.error(request, 'You are not authorized to view this page.')
        return redirect('index')

    # Get the customer
    customer = get_object_or_404(models.Customer, id=customer_id)

    # Optional: Check if the customer has had services at the worker's branch
    branch = worker.branch
    service_orders = models.ServiceRenderedOrder.objects.filter(customer=customer, branch=branch).order_by('-date')

    # Get customer's vehicles
    vehicles = models.CustomerVehicle.objects.filter(customer=customer)

    # Get loyalty transactions
    loyalty_transactions = models.LoyaltyTransaction.objects.filter(customer=customer).order_by('-date')

    # Get vehicle groups
    vehicle_groups = models.VehicleGroup.objects.all()

    context = {
        'customer': customer,
        'service_orders': service_orders,
        'vehicles': vehicles,
        'loyalty_transactions': loyalty_transactions,
        'vehicle_groups': vehicle_groups,
    }

    return render(request, 'layouts/workers/customer_detail.html', context)


@login_required(login_url='login')
def worker_profile(request):
    user = request.user

    # Check if the user is a worker
    worker = get_object_or_404(Worker, user=user)

    if request.method == 'POST':
        form = forms.WorkerProfileForm(request.POST, request.FILES, instance=worker)
        if form.is_valid():
            worker = form.save(commit=False)

            # Handle phone number update
            new_phone_number = form.cleaned_data.get('pending_phone_number')
            if new_phone_number != worker.user.phone_number:
                worker.pending_phone_number = new_phone_number
                worker.is_phone_number_approved = False  # Set to pending approval
                messages.info(request, 'Your phone number change is pending approval.')
            else:
                # No change in phone number
                worker.pending_phone_number = None
                worker.is_phone_number_approved = True

            worker.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('worker_profile')
    else:
        form = forms.WorkerProfileForm(instance=worker)

    # Calculate average rating
    completed_orders = ServiceRenderedOrder.objects.filter(workers__in=[worker], status='completed')
    total_ratings = completed_orders.aggregate(Sum('customer_rating'))['customer_rating__sum'] or 0
    rating_count = completed_orders.filter(customer_rating__isnull=False).count()
    average_rating = round(total_ratings / rating_count, 2) if rating_count > 0 else 0

    # Prepare star ratings
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


# ===========================================================================================================================================
# ========================================== Admin Views ====================================================================================
# ===========================================================================================================================================


@staff_member_required
def approve_workers(request):
    # Workers with GH Card details pending approval
    pending_gh_card_workers = Worker.objects.filter(
        is_gh_card_approved=False,
        gh_card_number__isnull=False
    ).exclude(gh_card_number__exact='')

    # Workers with phone number change pending approval
    pending_phone_workers = Worker.objects.filter(
        is_phone_number_approved=False,
        pending_phone_number__isnull=False
    ).exclude(pending_phone_number__exact='')

    context = {
        'pending_gh_card_workers': pending_gh_card_workers,
        'pending_phone_workers': pending_phone_workers,
    }

    return render(request, 'layouts/admin/approve_workers.html', context)


@staff_member_required
def approve_worker(request, worker_id, approval_type):
    worker = get_object_or_404(Worker, id=worker_id)
    if request.method == 'POST':
        if approval_type == 'gh_card':
            worker.is_gh_card_approved = True
            worker.save()
            messages.success(request, f"{worker.user.get_full_name()}'s GH Card details have been approved.")
        elif approval_type == 'phone':
            worker.is_phone_number_approved = True
            # Update the user's phone number
            worker.user.phone_number = worker.pending_phone_number
            worker.user.save()
            # Clear pending phone number
            worker.pending_phone_number = ''
            worker.save()
            messages.success(request, f"{worker.user.get_full_name()}'s phone number has been approved.")
        return redirect('approve_workers')
    else:
        messages.error(request, 'Invalid request.')
        return redirect('approve_workers')


# views.py

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta, datetime
from django.shortcuts import render


@staff_member_required
def admin_dashboard(request):
    # Branches
    branches = models.Branch.objects.all()

    # Data structures to hold analytics
    branch_data = []

    for branch in branches:
        # Total customers and vehicles
        branch_customers = models.Customer.objects.filter(servicerenderedorder__branch=branch).distinct().count()
        branch_vehicles = models.CustomerVehicle.objects.filter(
            customer__servicerenderedorder__branch=branch).distinct().count()

        branch_info = {
            'branch': branch,
            'total_customers': branch_customers,
            'total_vehicles': branch_vehicles,
        }

        branch_data.append(branch_info)

    # Total vehicle groups registered
    vehicle_groups_count = models.VehicleGroup.objects.count()

    now = timezone.now()
    today = now.date()
    start_of_month = today.replace(day=1)
    end_of_month = today

    # Branches
    branches = models.Branch.objects.all()

    # Variables to store highest revenue and services
    highest_revenue = 0
    highest_revenue_branch = None
    highest_services = 0
    highest_services_branch = None

    # Yearly data lists
    yearly_branch_names = []
    yearly_branch_revenues = []
    yearly_branch_services = []

    for branch in branches:
        # Monthly data
        month_orders = models.ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_of_month,
            date__date__lte=end_of_month
        )

        month_revenue = month_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        month_services = month_orders.count()

        # Update highest revenue
        if month_revenue > highest_revenue:
            highest_revenue = month_revenue
            highest_revenue_branch = branch

        # Update highest services
        if month_services > highest_services:
            highest_services = month_services
            highest_services_branch = branch

        # Yearly data
        start_of_year = today.replace(month=1, day=1)
        year_orders = models.ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_of_year,
            date__date__lte=end_of_month
        )

        year_revenue = year_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        year_services = year_orders.count()

        # Collect yearly data
        yearly_branch_names.append(branch.name)
        yearly_branch_revenues.append(year_revenue)
        yearly_branch_services.append(year_services)

        # ... existing code to collect branch_data ...

    # Serialize yearly data to JSON
    yearly_branch_names_json = json.dumps(yearly_branch_names)
    yearly_branch_revenues_json = json.dumps(yearly_branch_revenues)
    yearly_branch_services_json = json.dumps(yearly_branch_services)
    services = models.Service.objects.all()
    print(services)

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
    # Get the time period from the request
    time_period = request.GET.get('time_period', 'week')
    data_type = request.GET.get('data_type', 'revenue')  # 'revenue' or 'services'

    # Get current date
    today = timezone.now().date()

    # Determine date range based on the selected time period
    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())  # Start of the week (Monday)
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
            # If invalid month, default to current month
            month = today.month
            year = today.year
            start_date = datetime(year, month, 1).date()
            end_date = today

    # Branches
    branches = models.Branch.objects.all()

    branch_names = []
    branch_values = []

    for branch in branches:
        # Get service orders for the selected period
        branch_orders = models.ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date__gte=start_date,
            date__date__lte=end_date
        )

        # Calculate total revenue or services rendered based on data_type
        if data_type == 'revenue':
            total_value = branch_orders.aggregate(total=Sum('final_amount'))['total'] or 0
        else:  # 'services'
            total_value = branch_orders.count()

        branch_names.append(branch.name)
        branch_values.append(total_value)

    # Prepare the data to be returned as JSON
    data = {
        'branch_names': branch_names,
        'branch_values': branch_values,
    }

    return JsonResponse(data)


@staff_member_required
def get_service_performance_data(request):
    service_id = request.GET.get('service_id')
    time_period = request.GET.get('time_period', 'week')

    try:
        service = models.Service.objects.get(id=service_id)
    except models.Service.DoesNotExist:
        return JsonResponse({'error': 'Service does not exist'}, status=400)

    # Get current date
    today = timezone.now().date()

    # Determine date range based on the selected time period
    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())  # Start of the week (Monday)
        end_date = today
    elif time_period == 'month':
        start_date = today.replace(day=1)  # Start of the month
        end_date = today
    else:
        # Invalid time period, default to current month
        start_date = today.replace(day=1)
        end_date = today

    branches = models.Branch.objects.all()

    branch_names = []
    branch_values = []

    for branch in branches:
        service_rendered_orders_count = ServiceRendered.objects.filter(service_id=service_id,
                                                                       order__branch_id=branch.id,
                                                                       order__status='completed') \
            .values('order') \
            .distinct() \
            .count()

        # return service_rendered_orders_count
        total_services = service_rendered_orders_count
        branch_names.append(branch.name)
        branch_values.append(total_services)
    print(branch_names)
    print(branch_values)
    data = {
        'branch_names': branch_names,
        'branch_values': branch_values,
    }

    return JsonResponse(data)


@staff_member_required
def get_vehicles_data(request):
    # Get the time period from the request
    time_period = request.GET.get('time_period', 'week')

    # Get current date
    today = timezone.now().date()

    # Determine date range based on the selected time period
    if time_period == 'week':
        start_date = today - timedelta(days=today.weekday())  # Start of the week (Monday)
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
            # If invalid month, default to current month
            month = today.month
            year = today.year
            start_date = datetime(year, month, 1).date()
            end_date = today

    # Get customer vehicles added in the selected period
    vehicles = models.CustomerVehicle.objects.filter(
        date_added__gte=start_date,
        date_added__lte=end_date
    ).order_by('date_added')

    # Group vehicles by date
    date_counts = {}
    current_date = start_date
    while current_date <= end_date:
        date_counts[current_date.strftime('%Y-%m-%d')] = 0
        current_date += timedelta(days=1)

    for vehicle in vehicles:
        date_str = vehicle.date_added.strftime('%Y-%m-%d')
        if date_str in date_counts:
            date_counts[date_str] += 1
        else:
            date_counts[date_str] = 1

    # Prepare data for the chart
    dates = sorted(date_counts.keys())
    values = [date_counts[date] for date in dates]

    data = {
        'dates': dates,
        'values': values,
    }

    return JsonResponse(data)


@staff_member_required
def manage_workers(request):
    from . import models  # Ensure models are imported
    branch_id = request.GET.get('branch')
    if branch_id:
        workers = models.Worker.objects.filter(branch_id=branch_id)
    else:
        workers = models.Worker.objects.all()

    branches = models.Branch.objects.all()

    context = {
        'workers': workers,
        'branches': branches,
        'selected_branch': branch_id,
    }

    return render(request, 'layouts/admin/manage_workers.html', context)


@staff_member_required
def worker_detail(request, worker_id):
    from . import models  # Ensure models are imported
    worker = get_object_or_404(models.Worker, id=worker_id)

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

    context = {
        'worker': worker,
    }

    return render(request, 'layouts/admin/worker_detail.html', context)


@staff_member_required
def manage_customers(request):
    from . import models  # Ensure models are imported
    customers = models.Customer.objects.all()

    context = {
        'customers': customers,
    }

    return render(request, 'layouts/admin/manage_customers.html', context)


@staff_member_required
def customer_detail_admin(request, customer_id):
    from . import models  # Ensure models are imported
    customer = get_object_or_404(models.Customer, id=customer_id)
    vehicles = models.CustomerVehicle.objects.filter(customer=customer)
    service_orders = models.ServiceRenderedOrder.objects.filter(customer=customer).order_by('-date')

    context = {
        'customer': customer,
        'vehicles': vehicles,
        'service_orders': service_orders,
    }

    return render(request, 'layouts/admin/customer_detail_admin.html', context)


@staff_member_required
def vehicle_groups(request):
    from . import models  # Ensure models are imported
    vehicle_groups = models.VehicleGroup.objects.all()

    context = {
        'vehicle_groups': vehicle_groups,
    }

    return render(request, 'layouts/admin/vehicle_groups.html', context)


@staff_member_required
def manage_branches(request):
    branches = Branch.objects.all()
    context = {
        'branches': branches,
    }
    return render(request, 'layouts/admin/manage_branches.html', context)


@staff_member_required
def add_branch(request):
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Branch added successfully.')
            return redirect('manage_branches')
    else:
        form = BranchForm()
    context = {
        'form': form,
    }
    return render(request, 'layouts/admin/add_branch.html', context)


@staff_member_required
def edit_branch(request, branch_id):
    branch = get_object_or_404(Branch, id=branch_id)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            branch = form.save()

            # Handle branch head assignment
            branch_head_id = request.POST.get('branch_head')
            if branch_head_id:
                # Unassign previous branch head if any
                Worker.objects.filter(branch=branch, is_branch_head=True).update(is_branch_head=False)

                # Assign new branch head
                branch_head = Worker.objects.get(id=branch_head_id)
                branch_head.is_branch_head = True
                branch_head.save()
            messages.success(request, 'Branch updated successfully.')
            return redirect('manage_branches')
    else:
        form = BranchForm(instance=branch)
    # Get workers in this branch
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
    branch = get_object_or_404(Branch, id=branch_id)
    if request.method == 'POST':
        branch.delete()
        messages.success(request, 'Branch deleted successfully.')
        return redirect('manage_branches')
    context = {
        'branch': branch,
    }
    return render(request, 'layouts/admin/delete_branch.html', context)


from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Count, Avg


@staff_member_required
def branch_insights(request, branch_id):
    from . import models  # Ensure models are imported

    # Get the branch
    branch = get_object_or_404(models.Branch, id=branch_id)

    # Get the time period from the request (default to 'week')
    time_period = request.GET.get('time_period', 'week')

    # Determine date range based on time period
    today = timezone.now().date()
    if time_period == 'month':
        start_date = today.replace(day=1)
    else:  # Default to 'week'
        start_date = today - timedelta(days=today.weekday())  # Start of the week (Monday)

    # Define end_date
    end_date = today

    # Get dates in the range
    date_list = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    num_days = (end_date - start_date).days + 1  # Total number of days in the period

    # Prepare data for graphs
    services_data = []
    revenue_data = []
    dates = []

    has_data = False  # Flag to check if there's any data

    for date_item in date_list:
        services_count = models.ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date=date_item
        ).count()

        revenue_total = models.ServiceRenderedOrder.objects.filter(
            branch=branch,
            status='completed',
            date__date=date_item
        ).aggregate(total=Sum('final_amount'))['total'] or 0

        services_data.append(services_count)
        revenue_data.append(revenue_total)
        dates.append(date_item.strftime('%Y-%m-%d'))

        if services_count > 0 or revenue_total > 0:
            has_data = True  # Set flag to True if any data is found

    # Calculate average customers added per day
    customers = models.Customer.objects.filter(
        date_joined_app__gte=start_date,
        date_joined_app__lte=end_date
    )
    total_customers = customers.count()
    avg_customers_per_day = round(total_customers / num_days) if num_days > 0 else 0

    # Calculate average customer vehicles added per day
    vehicles = models.CustomerVehicle.objects.filter(
        date_added__gte=start_date,
        date_added__lte=end_date
    )
    total_vehicles = vehicles.count()
    avg_vehicles_per_day = total_vehicles / num_days if num_days > 0 else 0

    # Number of workers in the branch
    num_workers = models.Worker.objects.filter(branch=branch).count()

    # Average star rating of workers in the branch
    avg_worker_rating = models.Worker.objects.filter(
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
    total_revenue = models.Revenue.objects.filter(branch=branch, date=date).aggregate(total=Sum('final_amount'))[
                        'total'] or 0
    total_expenses = models.Expense.objects.filter(branch=branch, date=date).aggregate(total=Sum('amount'))[
                         'total'] or 0
    profit = total_revenue - total_expenses
    return profit


@staff_member_required
def analytics_dashboard(request):
    # Get the selected month and year from GET parameters
    selected_month = request.GET.get('month')
    selected_year = request.GET.get('year')

    today = timezone.now().date()
    current_year = today.year
    current_month = today.month

    # Define a list of months with their names
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

    # Define a range of years (e.g., from 2020 to current year)
    start_year = 2020
    years = list(range(start_year, current_year + 1))

    # Determine date range based on the selected time period (month)
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
            # If invalid month/year, default to current month
            start_date = today.replace(day=1)
            end_date = today
    else:
        # Default to current month
        start_date = today.replace(day=1)
        end_date = today

    # Fetch admin's daily expense budget
    try:
        admin_account = request.user.admin_profile
        daily_budget = admin_account.daily_expense_amount
    except models.AdminAccount.DoesNotExist:
        daily_budget = 0  # Default value if not set

    # Revenue Data
    revenue_data = models.Revenue.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name', 'date').annotate(total_revenue=Sum('final_amount'))

    # Expenses Data
    expenses_data = models.Expense.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name', 'date').annotate(total_expense=Sum('amount'))

    # Services Rendered Data
    services_data = models.ServiceRenderedOrder.objects.filter(
        branch__isnull=False,
        status='completed',
        date__date__gte=start_date,
        date__date__lte=end_date
    ).values('branch__name').annotate(total_services=Count('id'))

    # Products Sold Data
    products_sold_data = models.ProductPurchased.objects.filter(
        service_order__branch__isnull=False,
        service_order__date__date__gte=start_date,
        service_order__date__date__lte=end_date
    ).values('product__name').annotate(total_quantity=Sum('quantity'))

    # New Customer Vehicles Data
    new_vehicles_data = models.CustomerVehicle.objects.filter(
        date_added__date__gte=start_date,
        date_added__date__lte=end_date
    ).annotate(date_added_only=TruncDate('date_added')).values('date_added_only').annotate(total=Count('id')).order_by(
        'date_added_only')

    # Prepare data for charts (dates for the selected month)
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
    revenues = [date_counts[date]['revenue'] for date in dates]
    expenses = [date_counts[date]['expense'] for date in dates]

    # New Vehicles Added per day
    new_vehicles_dict = {entry['date_added_only'].strftime('%Y-%m-%d'): entry['total'] for entry in new_vehicles_data}
    new_vehicles = [new_vehicles_dict.get(date, 0) for date in dates]

    # Prepare Services Rendered per Branch
    services_branch_names = [entry['branch__name'] for entry in services_data]
    services_total_services = [entry['total_services'] for entry in services_data]

    # Prepare Products Sold Data
    products_sold_labels = [entry['product__name'] for entry in products_sold_data]
    products_sold_values = [entry['total_quantity'] for entry in products_sold_data]

    # Pass context to template
    context = {
        'months': months,
        'years': years,
        'selected_year': selected_year if selected_month and selected_year else current_year,
        'selected_month': selected_month if selected_month and selected_year else current_month,
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
    # [As defined above]
    # Fetch selected month and year
    selected_month = request.GET.get('month')
    selected_year = request.GET.get('year')

    today = timezone.now().date()
    current_year = today.year
    current_month = today.month

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
            # Invalid month/year, default to current month
            start_date = today.replace(day=1)
            end_date = today
    else:
        # Default to current month
        start_date = today.replace(day=1)
        end_date = today

    # Revenue Data
    revenue_data = models.Revenue.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name').annotate(total_revenue=Sum('final_amount'))

    # Expenses Data
    expenses_data = models.Expense.objects.filter(
        branch__isnull=False,
        date__gte=start_date,
        date__lte=end_date
    ).values('branch__name').annotate(total_expense=Sum('amount'))

    # Prepare a dictionary for easy lookup
    revenue_dict = {entry['branch__name']: entry['total_revenue'] for entry in revenue_data}
    expenses_dict = {entry['branch__name']: entry['total_expense'] for entry in expenses_data}

    branches = models.Branch.objects.all()
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
    user = request.user
    if user.is_staff or user.is_superuser:
        expenses = Expense.objects.all().order_by('-date')
    else:
        try:
            worker = user.worker_profile
            expenses = Expense.objects.filter(branch=worker.branch).order_by('-date')
        except Worker.DoesNotExist:
            messages.error(request, 'You are not authorized to view this page.')
            return redirect('index')
    return render(request, 'layouts/expense_list.html', {'expenses': expenses})


@login_required(login_url='login')
def add_expense(request):
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
    expense = get_object_or_404(Expense, pk=pk)
    user = request.user
    if not user.is_staff and not user.is_superuser and expense.user != user:
        messages.error(request, 'You are not authorized to edit this expense.')
        return redirect('expense_list')
    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense, user=user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = user
            expense.save()
            messages.success(request, 'Expense updated successfully.')
            return redirect('expense_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ExpenseForm(instance=expense, user=user)
    return render(request, 'layouts/edit_expense.html', {'form': form, 'expense': expense})


@login_required(login_url='login')
def delete_expense(request, pk):
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
