import uuid
from datetime import date

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

from autodash_App.commission_util import allocate_commission


# -------------Your existing imports and models (CustomUser, Branch, etc.)-------------
# Keep them as they are, just showing partial for brevity

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('worker', 'Worker'),
        ('customer', 'Customer'),
    )
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='customer')
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    approved = models.BooleanField(default=False)
    username = models.CharField(max_length=250, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.role}"


class Branch(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15)
    head_of_branch = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    date_opened = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.location}"


class WorkerCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    service_provider = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Worker(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='worker_profile', null=True, blank=True
    )
    worker_category = models.ForeignKey(
        'WorkerCategory', on_delete=models.SET_NULL,
        null=True, blank=True
    )
    gh_card_number = models.CharField(max_length=20, null=True, blank=True)
    gh_card_photo = models.ImageField(
        upload_to='gh_card_photos/', null=True, blank=True
    )
    is_gh_card_approved = models.BooleanField(default=False)

    # NEW personal & ID fields
    date_of_birth = models.DateField(null=True, blank=True)
    ecowas_id_card_no = models.CharField(max_length=50, null=True, blank=True)
    ecowas_id_card_photo = models.ImageField(
        upload_to='ecowas_id_photos/', null=True, blank=True
    )
    passport_photo = models.ImageField(
        upload_to='passport_photos/', null=True, blank=True
    )
    place_of_birth = models.CharField(max_length=100, null=True, blank=True)
    nationality = models.CharField(max_length=50, null=True, blank=True)
    home_address = models.TextField(null=True, blank=True)
    landmark = models.CharField(max_length=255, null=True, blank=True)

    # Educational
    year_of_admission = models.IntegerField(null=True, blank=True)

    # Employment
    position = models.CharField(max_length=100, null=True, blank=True)
    salary = models.FloatField(null=True, blank=True)

    # Branch admin flag
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='workers'
    )
    is_branch_admin = models.BooleanField(default=False)

    date_joined = models.DateField(default=timezone.now)
    rating_sum = models.FloatField(default=0)
    rating_count = models.IntegerField(default=0)
    pending_phone_number = models.CharField(max_length=15, null=True, blank=True)
    is_phone_number_approved = models.BooleanField(default=True)
    daily_commission = models.FloatField(default=0)

    def __str__(self):
        return f"{self.user.get_full_name()}  @ {self.branch.name}"

    def average_rating(self):
        return round(self.rating_sum / self.rating_count, 2) if self.rating_count else 0


# ---------------------------------------------------------------------
# RELATED INFO MODELS
# ---------------------------------------------------------------------
class WorkerEducation(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='educations')
    school_name = models.CharField(max_length=200, null=True, blank=True)
    school_location = models.CharField(max_length=200, null=True, blank=True)
    year_completed = models.IntegerField(null=True, blank=True)


class WorkerEmployment(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='employments')
    employer_name = models.CharField(max_length=200, null=True, blank=True)
    contact_number = models.CharField(max_length=20, null=True, blank=True)
    location = models.CharField(max_length=200, null=True, blank=True)
    position = models.CharField(max_length=100, null=True, blank=True)
    last_date_of_work = models.DateField(null=True, blank=True)
    home_office_address = models.TextField(null=True, blank=True)
    reason_for_leaving = models.CharField(max_length=255, null=True, blank=True)
    may_we_contact = models.BooleanField(default=False)


class WorkerReference(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='references')
    full_name = models.CharField(max_length=200, null=True, blank=True)
    mobile_number = models.CharField(max_length=20, null=True, blank=True)
    home_office_address = models.TextField(null=True, blank=True)


class WorkerGuarantor(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='guarantors')
    full_name = models.CharField(max_length=200, null=True, blank=True)
    mobile_number = models.CharField(max_length=20, null=True, blank=True)
    home_office_address = models.TextField(null=True, blank=True)


class VehicleGroup(models.Model):
    group_name = models.CharField(max_length=100, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    branches = models.ManyToManyField(Branch, related_name='vehiclegroups')

    def __str__(self):
        return f"{self.group_name}"


class AdminAccount(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='admin_profile')
    daily_expense_amount = models.FloatField(default=0)


class ServiceCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, null=True, blank=True)
    negotiable = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Service(models.Model):
    service_type = models.CharField(max_length=100)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='services', null=True,
                                      blank=True)
    category = models.ForeignKey(ServiceCategory, null=True, blank=True, on_delete=models.SET_NULL)
    description = models.TextField(null=True, blank=True)
    price = models.FloatField()
    branches = models.ManyToManyField(Branch, related_name='services')
    active = models.BooleanField(default=True)
    loyalty_points_earned = models.IntegerField(default=0)
    loyalty_points_required = models.IntegerField(default=0)
    commission_rate = models.FloatField(default=0.0)  # e.g. 10 => 10%

    def __str__(self):
        return f"{self.service_type} - {self.vehicle_group.group_name}"


class ProductCategory(models.Model):
    name = models.CharField(max_length=250, null=False, blank=False)
    description = models.TextField(null=False, blank=False)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey('ProductCategory', null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    price = models.FloatField()
    cost = models.FloatField()
    branch = models.ManyToManyField(Branch, related_name='products')
    stock = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.name} - GHS{self.price} - Stock: {self.stock}"


# ---------------------- New Model: Standalone Product Sales ----------------------
class ProductSale(models.Model):
    """
    A separate model to track product sales that are NOT tied to a service order,
    for purely standalone sales at each branch.
    """
    user = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='standalone_sales')
    batch_id = models.UUIDField(default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='product_sales')
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.FloatField()
    date_sold = models.DateTimeField(auto_now_add=True)
    customer = models.ForeignKey('Customer', null=True, blank=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        # Auto-set total price if not specified
        if not self.total_price:
            self.total_price = self.product.price * self.quantity

        # Decrement stock
        if self.pk is None:  # only reduce stock on initial creation
            if self.product.stock < self.quantity:
                raise ValueError("Not enough stock to complete this sale.")
            self.product.stock -= self.quantity
            self.product.save()

        super().save(*args, **kwargs)


# -------------- Customer and Subscription Models --------------
class Customer(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='customer_profile')
    date_joined_app = models.DateField(default=timezone.now)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='customers', null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)
    group_choices = (
        ("Cash", "Cash"),
        ("Credit", "Credit")
    )
    customer_group = models.CharField(max_length=250, null=True, blank=True, choices=group_choices)

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
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='vehicles', null=True, blank=True)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='vehicles', null=True,
                                      blank=True)
    car_plate = models.CharField(max_length=100, null=True, blank=True)
    car_make = models.CharField(max_length=100, null=True, blank=True)
    car_color = models.CharField(max_length=100, null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.customer:
            return f"{self.customer.user.first_name} - {self.car_make}({self.car_color}) - {self.car_plate}"
        return f"{self.car_make}({self.car_color}) - {self.car_plate}"

    def car_name(self):
        return f"{self.car_make}({self.car_color}) - {self.car_plate}"


class Subscription(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    amount = models.FloatField()
    duration_in_days = models.IntegerField()
    services = models.ManyToManyField(Service, related_name='subscriptions')
    vehicle_group = models.ManyToManyField(VehicleGroup, blank=True)

    def __str__(self):
        return f"{self.name}"


class CustomerSubscription(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='subscriptions')
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='subscriptions', null=True, blank=True)

    used_amount = models.FloatField(default=0.0, null=True, blank=True)  # track how much has been used
    sub_amount_remaining = models.FloatField(default=0.0, null=True, blank=True)
    last_rollover = models.DateTimeField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)
    latest_renewal_date = models.DateTimeField(null=True, blank=True)

    # or if you prefer you can compute on the fly from usage logs

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timezone.timedelta(days=self.subscription.duration_in_days)
        super().save(*args, **kwargs)

    def is_active(self):
        return self.end_date >= timezone.now().date()

    @property
    def remaining_balance(self):
        return self.subscription.amount - self.used_amount


class CustomerSubscriptionTrail(models.Model):
    subscription = models.ForeignKey(CustomerSubscription, on_delete=models.CASCADE)
    order = models.ForeignKey('ServiceRenderedOrder', on_delete=models.CASCADE)
    amount_used = models.FloatField()
    remaining_balance = models.FloatField()
    date_used = models.DateTimeField(auto_now_add=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.customer} {self.subscription}"


class CustomerSubscriptionRenewalTrail(models.Model):
    subscription = models.ForeignKey(CustomerSubscription, on_delete=models.CASCADE)
    date_renewed = models.DateTimeField(auto_now_add=True)
    amount_for_renewal = models.FloatField()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.customer} - Renewal for {self.subscription}"

    def renew(self):
        """
        Resets the used amount on the associated CustomerSubscription to 0
        and adds the renewal amount to the remaining balance.
        """
        # Reset used amount to zero
        self.subscription.used_amount = 0
        # Increase the remaining balance by the renewal amount
        self.subscription.sub_amount_remaining += self.amount_for_renewal
        self.subscription.save()


class LoyaltyTransaction(models.Model):
    TRANSACTION_CHOICES = (
        ('gain', 'Points Gained'),
        ('redeem', 'Points Redeemed'),
    )
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='loyalty_transactions')
    points = models.IntegerField()
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_CHOICES)
    description = models.TextField()
    order = models.ForeignKey('ServiceRenderedOrder', on_delete=models.CASCADE, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='loyalty_transactions', null=True,
                               blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.user.username} - {self.transaction_type} ({self.points}) on {self.date}"


# -------------- Core "Service Rendered" Models --------------
def generate_unique_order_number():
    import random, string
    prefix = "SRV"
    random_digits = ''.join(random.choices(string.digits, k=6))
    return f"{prefix}-{random_digits}"


class ServiceRenderedOrder(models.Model):
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('canceled', 'Canceled'),
        ('onCredit', 'On Credit'),
    ]
    service_order_number = models.CharField(max_length=100, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)
    workers = models.ManyToManyField(Worker, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending')
    total_amount = models.FloatField()
    amount_paid = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    discount_type = models.CharField(
        max_length=10,
        choices=[('percentage', 'Percentage'), ('amount', 'Amount')],
        default='amount'
    )
    discount_value = models.FloatField(default=0.0)
    customer_feedback = models.TextField(null=True, blank=True)
    customer_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True, blank=True
    )
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ('loyalty', 'Loyalty Points'),
            ('subscription', 'Subscription'),
            ('cash', 'Cash')
        ],
        null=True,
        blank=True
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='services_rendered',
        null=True,
        blank=True
    )
    comments = models.TextField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    time_in = models.DateTimeField(default=timezone.now)
    time_out = models.DateTimeField(null=True, blank=True)
    vehicle = models.ForeignKey(
        CustomerVehicle,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    # NEW FIELDS for usage breakdown
    subscription_amount_used = models.FloatField(null=True, blank=True, default=0.0)
    subscription_package_used = models.ForeignKey(CustomerSubscription, on_delete=models.SET_NULL, null=True,
                                                  blank=True)
    loyalty_points_used = models.FloatField(null=True, blank=True, default=0.0)
    loyalty_points_amount_deduction = models.FloatField(null=True,
                                                        blank=True)  # This shoes the amount that using the loyalty points saved the user which is useful for display on the receipt
    cash_paid = models.FloatField(null=True, blank=True, default=0.0)

    def __str__(self):
        if self.customer:
            return f"{self.service_order_number} - {self.customer.user.first_name} {self.customer.user.last_name}"
        return f"{self.service_order_number}"

    def save(self, *args, **kwargs):
        # If there's no order number, generate one
        if not self.service_order_number:
            self.service_order_number = generate_unique_order_number()
        super(ServiceRenderedOrder, self).save(*args, **kwargs)


class ServiceRendered(models.Model):
    order = models.ForeignKey('ServiceRenderedOrder', on_delete=models.CASCADE,
                              related_name='rendered', null=True, blank=True)
    service = models.ForeignKey('Service', on_delete=models.CASCADE,
                                related_name='services_rendered')
    workers = models.ManyToManyField('Worker', related_name='services_rendered', blank=True)
    date = models.DateTimeField(auto_now_add=True)
    commission_amount = models.FloatField(null=True, blank=True)
    negotiated_price = models.FloatField(null=True, blank=True)
    payment_type = models.CharField(max_length=200, null=True, blank=True, choices=(
        ("Loyalty Reward", "Loyalty Reward"), ("Subscription", "Subscription"), ("Cash", "Cash")))

    def __str_(self):
        return f"{self.service.service_type} on Vehicle {self.order.vehicle}"

    def get_effective_price(self):
        """Return negotiated price if present, else service price."""
        if self.negotiated_price is not None:
            return self.negotiated_price
        return self.service.price

    def allocate_commission(self, discount_factor=1):
        allocate_commission(self, discount_factor=discount_factor)

    def remove_commission(self):
        Commission.objects.filter(service_rendered=self).delete()
        self.commission_amount = 0.0
        self.save()

    def save(self, *args, **kwargs):
        # Optionally, compute commission upon creation if not set
        if self.service.commission_rate and self.commission_amount is None:
            self.commission_amount = (self.service.price * self.service.commission_rate) / 100
        super(ServiceRendered, self).save(*args, **kwargs)

    def save(self, *args, **kwargs):
        # Optionally compute initial commission if not set
        if self.pk is None and self.service.commission_rate and self.commission_amount is None:
            self.commission_amount = self.get_effective_price() * (self.service.commission_rate / 100.0)
        super().save(*args, **kwargs)


class Commission(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='commissions')
    service_rendered = models.ForeignKey(ServiceRendered, on_delete=models.CASCADE, related_name='commissions')
    amount = models.FloatField()
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.worker.user.get_full_name()} Commission on {self.date}: {self.amount}"


class ProductPurchased(models.Model):
    """
    Product purchased specifically as part of a ServiceRenderedOrder.
    """
    service_order = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='products_purchased')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchases')
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.FloatField()

    def save(self, *args, **kwargs):
        if not self.total_price:
            self.total_price = self.product.price * self.quantity

        # Decrement stock if it's a new purchase
        if self.pk is None:
            if self.product.stock < self.quantity:
                raise ValueError("Not enough stock to purchase this product.")
            self.product.stock -= self.quantity
            self.product.save()

        super(ProductPurchased, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} for Order {self.service_order.service_order_number}"


class Expense(models.Model):
    expense_choices = (
        ("Statutory", "Statutory"),
        ("Variable", "Variable"),
    )
    expense_category = models.CharField(max_length=250, null=True, blank=True, choices=expense_choices)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='expenses')
    description = models.TextField()
    amount = models.FloatField()
    date = models.DateField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='expenses', null=True, blank=True)

    # Optional fields to handle recurring (start_date, end_date, is_recurring, etc.)
    # e.g.
    is_recurring = models.BooleanField(default=False)

    # or you can store the frequency: daily, weekly, monthly, etc.

    def __str__(self):
        return f"{self.branch.name} Expense on {self.date}: {self.amount}"


class DailyExpenseBudget(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='daily_budgets')
    date = models.DateField()
    budgeted_amount = models.FloatField()

    def __str__(self):
        return f"{self.branch.name} Budget on {self.date}: {self.budgeted_amount}"


class Revenue(models.Model):
    """
    Tracks actual revenue (money that came in).
    If the service was onCredit or loyalty, the 'final_amount' might be 0 here
    or might not exist at all (since no real payment).
    """
    service_rendered = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='revenues',
                                         null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='revenues')
    amount = models.FloatField()
    discount = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='revenues', null=True, blank=True)
    profit = models.FloatField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Calculate profit or loss as final_amount - daily expenses
        # This is simplistic; you might refine how you define "profit"
        total_expenses = Expense.objects.filter(branch=self.branch, date=self.date).aggregate(total=Sum('amount'))[
                             'total'] or 0
        self.profit = (self.final_amount or 0) - total_expenses
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Revenue for {self.branch.name} on {self.date}: {self.amount}"


# ---------------- New Model to Track On-Credit Services (Arrears) ----------------
class Arrears(models.Model):
    """
    Tracks on-credit services (where final_amount wasn't paid by the customer).
    Once paid, record date_paid.
    """
    service_order = models.OneToOneField(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='arrears')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='arrears')
    amount_owed = models.FloatField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_paid = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Arrears - {self.service_order.service_order_number} - Owed: {self.amount_owed}"

    def mark_as_paid(self):
        self.is_paid = True
        self.date_paid = timezone.now()
        self.save()

        # Potentially create revenue record if the customer finally pays
        Revenue.objects.create(
            service_rendered=self.service_order,
            branch=self.branch,
            amount=self.amount_owed,
            final_amount=self.amount_owed,
            user=self.service_order.user,
            date=timezone.now().date()
        )


class WeeklyBudget(models.Model):
    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="weekly_budgets"
    )
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    budget_amount = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("branch", "weekday")
        ordering = ["weekday"]

    def __str__(self):
        return f"{self.branch.name} – {self.get_weekday_display()}: GHS{self.budget_amount:.2f}"


class RecurringExpense(models.Model):
    WEEKDAY_CHOICES = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    amount = models.FloatField()
    # You can choose either a specific date, or blanket every weekday/weekend, etc.
    apply_on = models.JSONField(
        default=list,
        help_text="List of weekdays (0=Mon … 6=Sun) or special dates"
    )

    def applies_today(self, date=None):
        """Return True if this expense should be created on `date`."""
        d = date or timezone.localdate()
        # by weekday:
        if d.weekday() in self.apply_on:
            return True
        # you could also store specific 'YYYY-MM-DD' strings in JSONField and test here
        return False

    def __str__(self):
        return f"{self.description} {self.amount}"


class SalesTarget(models.Model):
    FREQUENCY_WEEKLY = 'weekly'
    FREQUENCY_MONTHLY = 'monthly'
    FREQUENCY_CHOICES = [
        (FREQUENCY_WEEKLY, 'Weekly'),
        (FREQUENCY_MONTHLY, 'Monthly'),
    ]

    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='sales_targets')
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    target_amount = models.FloatField()

    class Meta:
        unique_together = ('branch', 'frequency')
        ordering = ['branch__name', 'frequency']

    def __str__(self):
        return f"{self.branch.name} – {self.get_frequency_display()} target: GHS {self.target_amount}"


class DailySalesTarget(models.Model):
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='daily_sales_targets'
    )
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    target_amount = models.FloatField(default=0.0)

    class Meta:
        unique_together = ('branch', 'weekday')
        ordering = ['branch__name','weekday']

    def __str__(self):
        return f"{self.branch.name} – {self.get_weekday_display()}: GHS {self.target_amount:.2f}"






