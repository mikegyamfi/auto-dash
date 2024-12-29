from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

from autodash_App import helper


# Custom User Model for both Workers and Customers
class CustomUser(AbstractUser):
    first_name = models.CharField(max_length=250, blank=True, null=True)
    last_name = models.CharField(max_length=250, blank=True, null=True)
    ROLE_CHOICES = (
        ('worker', 'Worker'),
        ('customer', 'Customer'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='customer')
    phone_number = models.CharField(max_length=15, null=False, blank=False, unique=True)
    email = models.EmailField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    approved = models.BooleanField(default=False)
    username = models.CharField(max_length=250, null=True, blank=True, unique=True)

    def __str__(self):
        return f"{self.username} - {self.role}"


# Branch Model
class Branch(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15)
    head_of_branch = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    date_opened = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.location}"


# Worker Model
class Worker(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='worker_profile')
    gh_card_number = models.CharField(max_length=20, null=True, blank=True)
    gh_card_photo = models.ImageField(upload_to='gh_card_photos/', null=True, blank=True)
    is_gh_card_approved = models.BooleanField(default=False)
    year_of_admission = models.IntegerField(null=True, blank=True)
    position = models.CharField(max_length=100, null=True, blank=True)
    salary = models.FloatField(null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='workers')
    date_joined = models.DateField(default=timezone.now)
    rating_sum = models.FloatField(default=0)
    rating_count = models.IntegerField(default=0)
    pending_phone_number = models.CharField(max_length=15, null=True, blank=True)
    is_phone_number_approved = models.BooleanField(default=True)
    is_branch_head = models.BooleanField(default=False)
    daily_commission = models.FloatField(default=0)

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} - ({self.branch.name})"

    def average_rating(self):
        if self.rating_count > 0:
            return round(self.rating_sum / self.rating_count, 2)
        return 0

    def add_rating(self, rating):
        self.rating_sum += rating
        self.rating_count += 1
        self.save()

    def add_commission(self, amount):
        self.daily_commission += amount
        self.save()


class VehicleGroup(models.Model):
    group_name = models.CharField(max_length=100, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    branches = models.ManyToManyField(Branch, related_name='vehiclegroups')

    def __str__(self):
        return f"{self.group_name}"


class AdminAccount(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='admin_profile')
    daily_expense_amount = models.FloatField(default=0)


# @receiver(post_save, sender=CustomUser)
# def create_admin_account(sender, instance, created, **kwargs):
#     if created and (instance.is_staff or instance.is_superuser):
#         AdminAccount.objects.create(user=instance)
#
#
# @receiver(post_save, sender=CustomUser)
# def save_admin_account(sender, instance, **kwargs):
#     if instance.is_staff or instance.is_superuser:
#         instance.admin_profile.save()


# Subscription Model
class Subscription(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    amount = models.FloatField()
    duration_in_days = models.IntegerField()
    services = models.ManyToManyField('Service', related_name='subscriptions')
    vehicle_group = models.ManyToManyField(VehicleGroup, null=True, blank=True)

    def __str__(self):
        return f"{self.name}"


# Customer Subscription Model
class CustomerSubscription(models.Model):
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='subscriptions')
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='subscriptions', null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timezone.timedelta(days=self.subscription.duration_in_days)
        super().save(*args, **kwargs)

    def is_active(self):
        return self.end_date >= timezone.now().date()


# Customer Model
class Customer(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='customer_profile')
    date_joined_app = models.DateField(default=timezone.now)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='customers', null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

    def add_loyalty_points(self, points, description='Points added'):
        self.loyalty_points += points
        self.save()
        LoyaltyTransaction.objects.create(
            customer=self,
            points=points,
            transaction_type='gain',
            description=description,
            branch=self.branch,
        )

    def apply_loyalty(self, points, description='Points redeemed'):
        if self.loyalty_points >= points:
            self.loyalty_points -= points
            self.save()
            LoyaltyTransaction.objects.create(
                customer=self,
                points=-points,
                transaction_type='redeem',
                description=description,
                branch=self.branch,
            )
            return True
        return False

    def can_redeem_service(self, service):
        return self.loyalty_points >= service.loyalty_points_required


class CustomerVehicle(models.Model):
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='vehicles', null=True, blank=True)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='vehicles', null=True,
                                      blank=True)
    car_plate = models.CharField(max_length=100, null=True, blank=True)
    car_make = models.CharField(max_length=100, null=True, blank=True)
    car_color = models.CharField(max_length=100, null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.user.first_name} - {self.car_make}({self.car_color}) - {self.car_plate}"


# Loyalty Transaction Model
class LoyaltyTransaction(models.Model):
    TRANSACTION_CHOICES = (
        ('gain', 'Points Gained'),
        ('redeem', 'Points Redeemed'),
    )
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='loyalty_transactions')
    points = models.IntegerField()
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_CHOICES)
    description = models.TextField()
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='loyalty_transactions', null=True,
                               blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.user.username} - {self.transaction_type} ({self.points}) on {self.date}"


# Service Model with Loyalty Points and Commission Rate
class Service(models.Model):
    service_type = models.CharField(max_length=100)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='services', null=True,
                                      blank=True)
    description = models.TextField(null=True, blank=True)
    price = models.FloatField()
    branches = models.ManyToManyField(Branch, related_name='services')
    active = models.BooleanField(default=True)
    loyalty_points_earned = models.IntegerField(default=0)
    loyalty_points_required = models.IntegerField(default=0)
    commission_rate = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.service_type} - {self.vehicle_group.group_name}"


def generate_unique_order_number():
    prefix = "SRV"  # You can customize this prefix as needed
    order_number = helper.generate_service_order_number(prefix)

    # Check if the generated service order number already exists
    while ServiceRenderedOrder.objects.filter(service_order_number=order_number).exists():
        order_number = helper.generate_service_order_number(prefix)  # Regenerate if it exists

    return order_number


# Service Rendered Order Model with updated discount handling
class ServiceRenderedOrder(models.Model):
    service_order_number = models.CharField(max_length=100, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    workers = models.ManyToManyField(Worker, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('canceled', 'Canceled'),
        ('onCredit', 'On Credit'),
    ]
    status = models.CharField(max_length=50,
                              choices=STATUS_CHOICES,
                              default='pending')
    total_amount = models.FloatField()
    amount_paid = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    discount_type = models.CharField(max_length=10,
                                     choices=[('percentage', 'Percentage'), ('amount', 'Amount')],
                                     default='amount')
    discount_value = models.FloatField(default=0.0)
    customer_feedback = models.TextField(null=True, blank=True)
    customer_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True,
                                          blank=True)
    payment_method = models.CharField(max_length=50,
                                      choices=[('loyalty', 'Loyalty Points'), ('subscription', 'Subscription'),
                                               ('cash', 'Cash')], null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='services_rendered', null=True,
                               blank=True)
    date = models.DateTimeField(auto_now_add=True)
    time_in = models.DateTimeField(default=timezone.now)
    time_out = models.DateTimeField(null=True, blank=True)
    vehicle = models.ForeignKey(CustomerVehicle, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.service_order_number} - {self.customer.user.first_name} {self.customer.user.last_name}"

    def save(self, *args, **kwargs):
        if not self.service_order_number:
            self.service_order_number = generate_unique_order_number()

        # Calculate final_amount based on discount_type and discount_value
        if self.discount_type == 'amount':
            self.final_amount = self.total_amount - self.discount_value
        elif self.discount_type == 'percentage':
            self.final_amount = self.total_amount - (self.total_amount * self.discount_value / 100)

        # Ensure final_amount is not negative
        if self.final_amount < 0:
            self.final_amount = 0

        super(ServiceRenderedOrder, self).save(*args, **kwargs)


# Service Rendered Model with Commission Calculation
class ServiceRendered(models.Model):
    order = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='rendered', null=True,
                              blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='services_rendered')
    workers = models.ManyToManyField(Worker, related_name='services_rendered', blank=True)
    date = models.DateTimeField(auto_now_add=True)
    commission_amount = models.FloatField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Calculate commission_amount based on service's commission_rate
        if self.service.commission_rate:
            self.commission_amount = (self.service.price * self.service.commission_rate) / 100
        else:
            self.commission_amount = 0.0

        super(ServiceRendered, self).save(*args, **kwargs)

        # Distribute commission among workers
        workers = self.workers.all()
        if workers:
            commission_per_worker = self.commission_amount / workers.count()
            for worker in workers:
                worker.add_commission(commission_per_worker)


# Commission Model to track commissions per worker per service rendered
class Commission(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='commissions')
    service_rendered = models.ForeignKey(ServiceRendered, on_delete=models.CASCADE, related_name='commissions')
    amount = models.FloatField()
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.worker.user.get_full_name()} Commission on {self.date}: {self.amount}"


# Expense Model to track daily expenses
class Expense(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='expenses')
    description = models.TextField()
    amount = models.FloatField()
    date = models.DateField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='expenses', null=True, blank=True)

    def __str__(self):
        return f"{self.branch.name} Expense on {self.date}: {self.amount}"


# Daily Expense Budget Model
class DailyExpenseBudget(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='daily_budgets')
    date = models.DateField()
    budgeted_amount = models.FloatField()

    def __str__(self):
        return f"{self.branch.name} Budget on {self.date}: {self.budgeted_amount}"


# Revenue Model with profit/loss calculation
class Revenue(models.Model):
    service_rendered = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='revenues',
                                         null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='revenues')
    amount = models.FloatField()
    discount = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='revenues', null=True, blank=True)
    profit = models.FloatField(null=True, blank=True)  # New field to track profit/loss

    def save(self, *args, **kwargs):
        # Calculate profit or loss
        # Sum of expenses for the date
        total_expenses = \
            Expense.objects.filter(branch=self.branch, date=self.date).aggregate(total=models.Sum('amount'))[
                'total'] or 0
        self.profit = self.final_amount - total_expenses
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Revenue for {self.branch.name} on {self.date}: {self.amount}"


class Product(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    price = models.FloatField()
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='products')
    stock = models.IntegerField(default=0)  # Available stock

    def __str__(self):
        return f"{self.name} - GHS{self.price} - Stock: {self.stock}"


# Product Purchased Model
class ProductPurchased(models.Model):
    service_order = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='products_purchased')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchases')
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.FloatField()

    def save(self, *args, **kwargs):
        if not self.total_price:
            self.total_price = self.product.price * self.quantity
        super(ProductPurchased, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} for Order {self.service_order.service_order_number}"
