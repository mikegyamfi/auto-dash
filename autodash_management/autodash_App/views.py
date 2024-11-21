import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Sum, Avg, functions
from django.db.models.functions import TruncDate
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import models, helper, forms


@login_required(login_url='login')
def home(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    user_role = user.role.lower()

    today = timezone.now().date()
    yesterday = today - timezone.timedelta(days=1)

    if user.is_superuser or user.is_staff:
        # Admin View
        branch_id = request.GET.get('branch_id')
        if not branch_id:
            # Render Branch Selection Page
            branches = models.Branch.objects.all()
            context = {
                'branches': branches,
            }
            return render(request, "layouts/admin/select_branch.html", context=context)
        else:
            # Validate and Get Selected Branch
            selected_branch = get_object_or_404(models.Branch, id=branch_id)

            # Revenue Calculations
            total_revenue_today = \
                models.Revenue.objects.filter(branch=selected_branch, date=today).aggregate(total=Sum('amount'))[
                    'total'] or 0
            total_revenue_yesterday = \
                models.Revenue.objects.filter(branch=selected_branch, date=yesterday).aggregate(total=Sum('amount'))[
                    'total'] or 0

            # Percentage Increase in Revenue
            if total_revenue_yesterday == 0 and total_revenue_today > 0:
                percentage_increase = 100
            elif total_revenue_yesterday > 0:
                percentage_increase = ((total_revenue_today - total_revenue_yesterday) / total_revenue_yesterday) * 100
            else:
                percentage_increase = 0

            # Services Rendered Calculations
            services_rendered_today = models.ServiceRenderedOrder.objects.filter(
                branch=selected_branch,
                date__date=today
            ).count()

            services_rendered_yesterday = models.ServiceRenderedOrder.objects.filter(
                branch=selected_branch,
                date__date=yesterday
            ).count()

            # Percentage Change in Services Rendered
            if services_rendered_yesterday == 0 and services_rendered_today > 0:
                percentage_change = 100
            elif services_rendered_yesterday > 0:
                percentage_change = ((
                                             services_rendered_today - services_rendered_yesterday) / services_rendered_yesterday) * 100
            else:
                percentage_change = 0

            # Expenses Calculations
            total_expenses_today = \
                models.Expense.objects.filter(branch=selected_branch, date=today).aggregate(total=Sum('amount'))[
                    'total'] or 0

            # Orders Calculations
            pending_orders_today = models.ServiceRenderedOrder.objects.filter(
                branch=selected_branch,
                status='pending',
                date__date=today
            ).count()

            completed_orders = models.ServiceRenderedOrder.objects.filter(
                branch=selected_branch,
                status='completed'
            ).count()

            on_credit_orders = models.ServiceRenderedOrder.objects.filter(
                branch=selected_branch,
                payment_method='credit'
            ).count()

            # Commission Calculations
            total_commission = models.Commission.objects.filter(
                service_rendered__order__branch=selected_branch,
                date=today
            ).aggregate(total=Sum('amount'))['total'] or 0

            # Products Sold Calculations
            products_sold_today = models.ProductPurchased.objects.filter(
                service_order__branch=selected_branch,
                service_order__date__date=today
            ).aggregate(total=Sum('quantity'))['total'] or 0

            # Revenue Generated Calculations
            revenue_generated = models.Revenue.objects.filter(
                branch=selected_branch,
                date=today
            ).aggregate(total=Sum('final_amount'))['total'] or 0

            # Aggregate Data for Admin Dashboard
            context = {
                'user': user,
                'branch': selected_branch,
                'revenue_today': total_revenue_today,
                'percentage_increase': round(percentage_increase, 2),
                'services_rendered_today': services_rendered_today,
                'services_percentage_change': round(percentage_change, 2),
                'expenses_today': total_expenses_today,
                'pending_orders_today': pending_orders_today,
                'completed_orders': completed_orders,
                'on_credit_orders': on_credit_orders,
                'total_commission': total_commission,
                'products_sold_today': products_sold_today,
                'revenue_generated': revenue_generated,
                'branches': models.Branch.objects.all(),  # For branch selection UI
            }

            return render(request, "layouts/admin/dashboard.html", context=context)

    elif user_role == 'worker':
        # Worker View
        account = models.Worker.objects.get(user=user)
        branch = account.branch

        # Revenue Calculations
        total_revenue_today = models.Revenue.objects.filter(branch=branch, date=today).aggregate(total=Sum('amount'))[
                                  'total'] or 0
        total_revenue_yesterday = \
            models.Revenue.objects.filter(branch=branch, date=yesterday).aggregate(total=Sum('amount'))['total'] or 0

        # Percentage Increase in Revenue
        if total_revenue_yesterday == 0 and total_revenue_today > 0:
            percentage_increase = 100
        elif total_revenue_yesterday > 0:
            percentage_increase = ((total_revenue_today - total_revenue_yesterday) / total_revenue_yesterday) * 100
        else:
            percentage_increase = 0

        # Services Rendered Calculations
        services_rendered_today = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            date__date=today
        ).count()

        services_rendered_yesterday = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            date__date=yesterday
        ).count()

        # Percentage Change in Services Rendered
        if services_rendered_yesterday == 0 and services_rendered_today > 0:
            percentage_change = 100
        elif services_rendered_yesterday > 0:
            percentage_change = ((
                                         services_rendered_today - services_rendered_yesterday) / services_rendered_yesterday) * 100
        else:
            percentage_change = 0

        # Expenses Calculations
        total_expenses_today = models.Expense.objects.filter(branch=branch, date=today).aggregate(total=Sum('amount'))[
                                   'total'] or 0

        # Orders Calculations
        pending_orders_today = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            status='pending',
            date__date=today
        ).count()

        completed_orders = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            status='completed'
        ).count()

        on_credit_orders = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            payment_method='credit',
            branch=branch
        ).count()

        # Commission Calculations
        total_commission = models.Commission.objects.filter(
            worker=account,
            date=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Products Sold Calculations
        products_sold_today = models.ProductPurchased.objects.filter(
            service_order__workers=account,
            service_order__branch=branch,
            service_order__date__date=today
        ).aggregate(total=Sum('quantity'))['total'] or 0

        # Revenue Generated Calculations
        revenue_generated = models.Revenue.objects.filter(
            branch=branch,
            date=today
        ).aggregate(total=Sum('final_amount'))['total'] or 0

        # Rating Calculations
        completed_orders_with_rating = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            status='completed',
            customer_rating__isnull=False
        )
        total_ratings = completed_orders_with_rating.aggregate(Sum('customer_rating'))['customer_rating__sum'] or 0
        rating_count = completed_orders_with_rating.count()
        average_rating = round(total_ratings / rating_count, 2) if rating_count > 0 else 0

        # Recent Services
        recent_services = completed_orders_with_rating.order_by('-date')[:5]

        # Pending Services (Last 5)
        pending_orders = models.ServiceRenderedOrder.objects.filter(
            workers=account,
            status='pending'
        ).order_by('-date')[:5]

        # Aggregate Data for Worker Dashboard
        context = {
            'user': user,
            'account': account,
            'branch': branch,
            'revenue_today': total_revenue_today,
            'percentage_increase': round(percentage_increase, 2),
            'services_rendered_today': services_rendered_today,
            'services_percentage_change': round(percentage_change, 2),
            'expenses_today': total_expenses_today,
            'pending_orders_today': pending_orders_today,
            'completed_orders': completed_orders,
            'on_credit_orders': on_credit_orders,
            'total_commission': total_commission,
            'products_sold_today': products_sold_today,
            'revenue_generated': revenue_generated,
            'average_rating': average_rating,
            'services_count': completed_orders_with_rating.count(),
            'recent_services': recent_services,
            'pending_services': pending_orders,
        }

        return render(request, "layouts/index.html", context=context)

    elif user_role == 'customer':
        # Redirect Customers to Their Dashboard
        return redirect('customer_dashboard')

    else:
        # Handle Undefined Roles
        messages.info(request, 'You are not allowed to access this page.')
        return redirect('index')


# def service(request):
#     return render(request, "layouts/service.html")


from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from .models import Customer, Worker, Service, ServiceRendered, Subscription, CustomerSubscription, CustomUser, \
    ServiceRenderedOrder, Revenue, Branch
from .forms import LogServiceForm, NewCustomerForm, BranchForm
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

    # Initialize total_amount as the sum of all service prices
    total_amount = sum([service_rendered.service.price for service_rendered in services_rendered])
    final_amount = total_amount  # Start with total_amount

    # GET request processing
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

                # Loop through services rendered
                for service_rendered in services_rendered:
                    service = service_rendered.service
                    vehicle = service_order.vehicle  # Ensure ServiceRenderedOrder has a 'vehicle' field
                    vehicle_group = vehicle.vehicle_group if vehicle else None

                    # Check if service and vehicle group are covered
                    if service in subscription_services and vehicle_group in subscription_vehicle_groups:
                        final_amount -= service.price

                # Ensure final_amount is not negative
                final_amount = max(final_amount, 0)

        except models.CustomerSubscription.DoesNotExist:
            active_subscription = False
            customer_subscription = None

        # Save the total_amount and final_amount to service_order
        service_order.total_amount = total_amount
        service_order.final_amount = final_amount
        service_order.save()

        context = {
            'service_order': service_order,
            'services': services_rendered,
            'loyalty_points': loyalty_points,
            'active_subscription': active_subscription,
            'subscription': customer_subscription,
            'service_customer': customer,
        }
        return render(request, "layouts/workers/confirm_service_order.html", context=context)

    # POST request processing
    elif request.method == 'POST':
        service_order.status = "completed"
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
            # Deduct the service price from the final amount
            final_amount -= service_rendered.service.price
            # Deduct loyalty points from the customer
            customer.loyalty_points -= service_rendered.service.loyalty_points_required
            # Record the loyalty redemption transaction
            models.LoyaltyTransaction.objects.create(
                customer=customer,
                points=-service_rendered.service.loyalty_points_required,
                transaction_type="redeem",
                description=f'Redeemed for {service_rendered.service.service_type}',
                branch=worker.branch,
            )

        # Ensure final_amount is not negative
        final_amount = max(final_amount, 0)

        # Get discount percentage from POST data
        discount_percentage = float(request.POST.get('discount', '0'))
        discount_percentage = min(max(discount_percentage, 0), 100)  # Clamp between 0 and 100

        # Calculate discount amount
        discount_amount = (float(final_amount) * float(discount_percentage)) / 100

        # Adjust final amount
        final_amount -= discount_amount

        # Ensure final_amount is not negative
        final_amount = max(final_amount, 0)

        # Save the discount to the service_order
        service_order.discount = float(discount_amount)  # Assuming 'discount' field stores the discount amount
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

        # Send Feedback URL (Optional)
        feedback_url = f"http://localhost:8000/feedback/{service_order.id}"
        service_names = ', '.join([service_rendered.service.service_type for service_rendered in services_rendered])

        # Format the SMS message
        message = (
            f"Thank you for your patronage #{service_order.service_order_number}. "
            f"Services rendered: {service_names}. Total: GHS{service_order.final_amount}. "
            f"Please provide your feedback as it helps us improve our services: {feedback_url}"
        )

        print(message)
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
        form = NewCustomerForm(request.POST)
        if form.is_valid():
            new_custom_user = form.save(commit=False)

            new_custom_user.role = 'customer'
            new_custom_user.save()

            new_custom_user.username = form.cleaned_data['phone_number']
            new_custom_user.save()

            new_customer = models.Customer.objects.create(user=new_custom_user)
            new_customer.save()

            print("customer saved")

            # Send password reset email to new customer
            send_password_reset(new_custom_user)

            return JsonResponse({
                'success': True,
            })
        return JsonResponse({'success': False})

    return JsonResponse({'success': False})


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
    user = models.CustomUser.objects.get(id=request.user.id)
    worker = models.Worker.objects.get(user=user)
    services_rendered = ServiceRenderedOrder.objects.filter(workers__in=[worker]).order_by('-date')[:20]
    print(services_rendered)
    return render(request, 'layouts/workers/service_history.html', {'services_rendered': services_rendered})


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
    ).annotate(date_added_only=TruncDate('date_added')).values('date_added_only').annotate(total=Count('id')).order_by('date_added_only')

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
