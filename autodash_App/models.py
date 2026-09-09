import uuid
from datetime import date

from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

from autodash_App.commission_util import allocate_commission, allocate_other_service_commission


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
    alternate_phone_number = models.CharField(max_length=15, null=True, blank=True)
    network_choices = (
        ("MTN", "MTN"),
        ("AT", "AT"),
        ("Telecel", "Telecel"),
    )
    momo_number_network = models.CharField(max_length=15, null=True, blank=True)
    momo_number = models.CharField(max_length=15, null=True, blank=True)
    momo_name = models.CharField(max_length=100, null=True, blank=True)
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

    # Per-worker daily productivity targets (fed into the scorecard).
    daily_orders_target = models.FloatField(default=0, help_text="Target number of service orders per day.")
    daily_services_target = models.FloatField(default=0, help_text="Target number of services rendered per day.")
    daily_value_target = models.FloatField(
        default=0,
        help_text="Target value (GHS) of services this worker is expected to generate per day.",
    )

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
    service_class_choices = (
        ('Detailing', 'Detailing'),
        ('Non-Detailing', 'Non-Detailing'),
    )
    service_class = models.CharField(max_length=100, null=True, blank=True, choices=service_class_choices, default='Non-Detailing')
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
        vg = self.vehicle_group.group_name if self.vehicle_group else "No Group"
        return f"{self.service_type} - {vg}"


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


class ProductStockLog(models.Model):
    CHANGE_TYPES = (
        ('restock', 'Restock (Addition)'),
        ('adjustment', 'Adjustment (Overwrite)'),
        ('sale', 'Sale (Deduction)'),
    )

    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='stock_logs')
    user = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE)  # Track which branch triggered it

    change_type = models.CharField(max_length=20, choices=CHANGE_TYPES)
    quantity_changed = models.IntegerField(help_text="The amount added or removed")
    old_quantity = models.IntegerField()
    new_quantity = models.IntegerField()

    notes = models.TextField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.product.name} - {self.change_type} ({self.quantity_changed})"


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
        if not self.total_price:
            self.total_price = self.product.price * self.quantity

        # # Decrement stock
        # if self.pk is None:  # only reduce stock on initial creation
        #     if self.product.stock < self.quantity:
        #         raise ValueError("Not enough stock to complete this sale.")
        #     self.product.stock -= self.quantity
        #     self.product.save()

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
    initial_sms_sent = models.BooleanField(default=False)
    completed_sms_sent = models.BooleanField(default=False)
    credit_sms_sent = models.BooleanField(default=False)
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
            ('cash', 'Cash'),
            ('momo', 'MoMo'),
            ('card', 'Card'),
            ('split', 'Split'),
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
    momo_amount = models.FloatField(null=True, blank=True, default=0.0)
    card_amount = models.FloatField(null=True, blank=True, default=0.0)
    is_walkin = models.BooleanField(default=False)
    walkin_name = models.CharField(max_length=150, null=True, blank=True)
    walkin_phone = models.CharField(max_length=20, null=True, blank=True)
    walkin_vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.SET_NULL, null=True, blank=True)
    walkin_vehicle_make = models.CharField(max_length=100, null=True, blank=True)
    walkin_vehicle_plate = models.CharField(max_length=50, null=True, blank=True)

    @property
    def display_customer_name(self):
        if self.customer:
            return f"{self.customer.user.first_name} {self.customer.user.last_name}"
        return self.walkin_name or "Walk-In Customer"

    @property
    def display_vehicle_info(self):
        if self.vehicle:
            return f"{self.vehicle.car_plate} ({self.vehicle.car_make})"
        return f"{self.walkin_vehicle_plate} ({self.walkin_vehicle_make})"

    @property
    def display_date(self):
        return self.date

    @property
    def record_type(self):
        return "core"

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
        ("Loyalty Reward", "Loyalty Reward"), ("Subscription", "Subscription"), ("Cash", "Cash"),  ("MoMo", "MoMo")))

    def __str__(self):
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
        # commission_amount is a CACHE of what allocate_commission actually paid
        # out, so it must not be guessed at creation time: a line saved before
        # its workers are attached would otherwise claim a commission that has
        # no Commission rows behind it, and every report reading this field
        # would overstate. It stays 0 until allocation writes the real figure.
        if self.pk is None and self.commission_amount is None:
            self.commission_amount = 0.0
        super().save(*args, **kwargs)


class Commission(models.Model):
    """
    One worker's cut of one job. The job is either a catalogue line
    (`service_rendered`) or a non-catalogue job (`other_service`) — exactly one
    of the two is set. Reports aggregate on `worker`/`date`, so both kinds are
    picked up without the caller having to know which is which.
    """
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='commissions')
    service_rendered = models.ForeignKey(
        ServiceRendered, on_delete=models.CASCADE, related_name='commissions',
        null=True, blank=True,
    )
    other_service = models.ForeignKey(
        "OtherService", on_delete=models.CASCADE, related_name='commissions',
        null=True, blank=True,
    )
    amount = models.FloatField()
    # Deliberately NOT auto_now_add: that stamps the row with whenever
    # allocation last ran, so re-touching an old job drags its commission into
    # today's reports while the revenue stays in the original period. The
    # allocator sets this from the job's own date instead.
    date = models.DateField(default=timezone.localdate)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(service_rendered__isnull=False, other_service__isnull=True)
                    | Q(service_rendered__isnull=True, other_service__isnull=False)
                ),
                name="commission_exactly_one_source",
            ),
            # Idempotency is enforced by the database, not merely assumed by
            # update_or_create: one row per worker per job, so a double
            # allocation can never quietly pay someone twice.
            models.UniqueConstraint(
                fields=["worker", "service_rendered"],
                name="commission_unique_worker_per_line",
            ),
            models.UniqueConstraint(
                fields=["worker", "other_service"],
                name="commission_unique_worker_per_other_service",
            ),
        ]

    @property
    def source_name(self):
        """What the commission was earned on, for reports and exports."""
        if self.service_rendered_id and self.service_rendered.service_id:
            return self.service_rendered.service.service_type
        if self.other_service_id:
            return self.other_service.service_name
        return ""

    @property
    def is_other_service(self):
        return self.other_service_id is not None

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

    # Classification: everything here is an expense, but operating costs are
    # reported separately (they come off Net Sales) from everything else.
    TYPE_OPERATING = "operating"
    TYPE_OTHER = "other"
    TYPE_CHOICES = (
        (TYPE_OPERATING, "Operating"),
        (TYPE_OTHER, "Other"),
    )
    expense_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER,
        help_text="Operating = day-to-day running cost (incl. utilities). "
                  "Other = everything non-operational.",
    )
    # Set on rows created automatically (e.g. utility usage) so they can be
    # told apart from what a manager typed in.
    is_auto_generated = models.BooleanField(default=False)

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
    service_rendered = models.OneToOneField(
        "ServiceRenderedOrder",
        on_delete=models.CASCADE,
        related_name="revenues",
        null=True, blank=True,
        unique=True
    )
    other_service = models.OneToOneField(
        "OtherService",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="revenue"
    )
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
    Once paid, record date_paid and how the payment was split between cash / momo.
    """
    service_order = models.OneToOneField(
        ServiceRenderedOrder, on_delete=models.CASCADE, related_name='arrears',
        null=True, blank=True,
    )
    other_service = models.OneToOneField(
        "OtherService", on_delete=models.CASCADE, related_name='arrears',
        null=True, blank=True,
    )
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='arrears')
    amount_owed = models.FloatField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_paid = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    paid_cash_amount = models.FloatField(default=0.0, help_text="Portion of arrears paid in cash.")
    paid_momo_amount = models.FloatField(default=0.0, help_text="Portion of arrears paid via MoMo.")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(service_order__isnull=False, other_service__isnull=True)
                    | Q(service_order__isnull=True, other_service__isnull=False)
                ),
                name="arrears_exactly_one_source",
            ),
        ]

    # ---- dual-source accessors ------------------------------------------
    # A debt is owed on either a service order or a non-catalogue job. These let
    # reports, exports and templates read one shape regardless of which.
    @property
    def job(self):
        return self.service_order if self.service_order_id else self.other_service

    @property
    def is_other_service(self):
        return self.other_service_id is not None

    @property
    def display_reference(self):
        if self.service_order_id:
            return self.service_order.service_order_number or f"#{self.service_order_id}"
        if self.other_service_id:
            return self.other_service.display_reference
        return "-"

    @property
    def display_description(self):
        """What the debt is for."""
        if self.service_order_id:
            return ", ".join(
                sr.service.service_type for sr in self.service_order.rendered.all()
            ) or "N/A"
        if self.other_service_id:
            return self.other_service.service_name
        return "N/A"

    @property
    def display_customer_name(self):
        if self.service_order_id:
            return self.service_order.display_customer_name
        if self.other_service_id:
            return self.other_service.contact_name or "N/A"
        return "N/A"

    @property
    def display_customer_phone(self):
        """The number to chase, whichever kind of job this is."""
        if self.service_order_id:
            order = self.service_order
            if order.customer and order.customer.user.phone_number:
                return order.customer.user.phone_number
            return order.walkin_phone or ""
        if self.other_service_id:
            return self.other_service.contact_phone or ""
        return ""

    def __str__(self):
        return f"Arrears - {self.display_reference} - Owed: {self.amount_owed}"

    def mark_as_paid(self):
        self.is_paid = True
        self.date_paid = timezone.now()
        self.save()

        # Potentially create revenue record if the customer finally pays
        job = self.job
        link = (
            {"service_rendered": self.service_order} if self.service_order_id
            else {"other_service": self.other_service}
        )
        Revenue.objects.update_or_create(
            defaults=dict(
                branch=self.branch,
                amount=self.amount_owed,
                final_amount=self.amount_owed,
                user=job.user if job else None,
                date=timezone.now(),
            ),
            **link,
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


class RecurringPaymentSetup(models.Model):
    """
    The master configuration for a recurring bill (e.g., 'Facility Rent', GHS 100 on Mondays).
    """
    WEEKDAY_CHOICES = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]

    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='recurring_setups')
    description = models.CharField(max_length=255)
    base_amount = models.FloatField(help_text="The baseline amount due every time this triggers.")
    apply_on = models.JSONField(
        default=list,
        help_text="List of weekdays (0=Mon … 6=Sun) this payment is due."
    )

    def applies_today(self, d=None):
        d = d or timezone.localdate()
        return d.weekday() in self.apply_on

    def __str__(self):
        return f"{self.description} - GHS {self.base_amount} ({self.branch.name})"


class DailyPaymentTarget(models.Model):
    """
    The actual generated bill for a specific day. Tracks rollover debt and actual payments.
    """
    setup = models.ForeignKey(RecurringPaymentSetup, on_delete=models.CASCADE, related_name='daily_targets')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='payment_targets')
    date = models.DateField(default=timezone.now)

    # The Math
    base_amount = models.FloatField(default=0.0, help_text="What is due just for today")
    brought_forward = models.FloatField(default=0.0, help_text="Unpaid debt rolled over from previous days")
    total_target = models.FloatField(default=0.0, help_text="Base Amount + Brought Forward")

    # The Action
    amount_paid = models.FloatField(default=0.0, help_text="How much was actually paid towards this today")
    is_settled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('setup', 'date')
        ordering = ['-date', 'setup__description']

    def save(self, *args, **kwargs):
        # Auto-calculate the total target and settlement status before saving
        self.total_target = self.base_amount + self.brought_forward
        self.is_settled = self.amount_paid >= self.total_target
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.setup.description} [{self.date}] - Due: GHS {self.total_target}"


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
        ordering = ['branch__name', 'weekday']

    def __str__(self):
        return f"{self.branch.name} – {self.get_weekday_display()}: GHS {self.target_amount:.2f}"


class WorkerDailyAdjustment(models.Model):
    """
    Bonus / deduction the manager keys in for a given worker-day.
    `branch` is filled automatically from the worker.
    """
    worker = models.ForeignKey(
        Worker, on_delete=models.CASCADE, related_name="daily_adjustments"
    )
    date = models.DateField()
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)

    bonus = models.FloatField(default=0.0)
    deduction = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("worker", "date")
        ordering = ["-date", "worker__user__last_name"]

    @property
    def total_earnings(self):
        commission = (
                Commission.objects
                .filter(worker=self.worker, date=self.date)
                .aggregate(total=Sum("amount"))["total"] or 0
        )
        return commission - self.deduction + self.bonus

    # ────────────────────────────────────────────────────────────────
    # automatically copy worker.branch → branch on save
    # ────────────────────────────────────────────────────────────────
    def save(self, *args, **kwargs):
        # When the worker is set/changed, default branch from it
        if self.worker_id and (self.branch_id is None or self.branch_id != self.worker.branch_id):
            self.branch = self.worker.branch

            # If the caller passed update_fields, make sure "branch"
            # is included so Django actually writes the column.
            uf = kwargs.get("update_fields")
            if uf is not None:
                kwargs["update_fields"] = set(uf) | {"branch"}

        super().save(*args, **kwargs)


class CustomerBooking(models.Model):
    STATUS_CHOICES = [
        ("booked", "Booked"),
        ("arrived", "Arrived"),
        ("canceled", "Canceled"),
        ("converted", "Converted to Service Order"),
    ]

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="bookings"
    )
    vehicle = models.ForeignKey(
        CustomerVehicle, on_delete=models.CASCADE, related_name="bookings"
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name="customer_bookings",
        null=True, blank=True
    )
    services = models.ManyToManyField(
        Service, related_name="bookings", blank=False
    )

    # Logistics
    driver_name = models.CharField(max_length=120, null=True, blank=True)
    driver_phone = models.CharField(max_length=20, null=True, blank=True)
    scheduled_at = models.DateTimeField(help_text="When the vehicle is expected in.")
    notes = models.TextField(null=True, blank=True)

    # Lifecycle
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="booked")
    arrived_at = models.DateTimeField(null=True, blank=True, help_text="Actual time vehicle arrived.")
    converted_at = models.DateTimeField(null=True, blank=True, help_text="When it became a Service Order.")
    converted_to_order = models.BooleanField(default=False)

    # Link to created order (optional; set when converting)
    service_order = models.ForeignKey(
        ServiceRenderedOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="from_booking"
    )

    # Bookkeeping
    booking_reference = models.CharField(max_length=24, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scheduled_at"]
        indexes = [
            models.Index(fields=["customer", "scheduled_at"]),
            models.Index(fields=["branch", "scheduled_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Booking {self.booking_reference or '#'} – {self.customer} – {self.vehicle}"

    def save(self, *args, **kwargs):
        if not self.booking_reference:
            self.booking_reference = self._generate_ref()
        super().save(*args, **kwargs)

    # Helpers
    @staticmethod
    def _generate_ref():
        import random, string
        prefix = "BKG"
        digits = "".join(random.choices(string.digits, k=6))
        return f"{prefix}-{digits}"

    @property
    def is_past_due(self):
        return self.status == "booked" and self.scheduled_at < timezone.now()

    def mark_arrived(self, when=None):
        self.status = "arrived"
        self.arrived_at = when or timezone.now()

    def mark_converted(self, order: ServiceRenderedOrder, when=None):
        self.status = "converted"
        self.converted_to_order = True
        self.service_order = order
        self.converted_at = when or timezone.now()


class Notification(models.Model):
    LEVEL_INFO = 'info'
    LEVEL_SUCCESS = 'success'
    LEVEL_WARNING = 'warning'
    LEVEL_ERROR = 'error'
    LEVEL_CHOICES = [
        (LEVEL_INFO, 'Info'),
        (LEVEL_SUCCESS, 'Success'),
        (LEVEL_WARNING, 'Warning'),
        (LEVEL_ERROR, 'Error'),
    ]

    # who should see this notification
    # recipient = models.ForeignKey(
    #     CustomUser,
    #     on_delete=models.CASCADE,
    #     related_name='notifications'
    # )

    # optional grouping info (useful when you want to notify staff of a branch)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications'
    )

    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="")
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=LEVEL_INFO)

    # Optional: a URL to “view details” (booking detail, convert page, etc.)
    target_url = models.URLField(max_length=500, null=True, blank=True)

    # unread/read states
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_level_display()}] {self.title}"

    def mark_read(self, when=None):
        if not self.is_read:
            self.is_read = True
            self.read_at = when or timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class OtherService(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
        ('onCredit', 'On Credit'),
    ]

    # who logged it
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="other_services")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="other_services")

    # core fields
    service_name = models.CharField(max_length=200)
    amount = models.FloatField(validators=[MinValueValidator(0.0)])
    workers = models.ManyToManyField('Worker', related_name='other_services_rendered', blank=True)
    contact_name = models.CharField(max_length=120, blank=True, default="")
    contact_phone = models.CharField(max_length=30, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Payment breakdown. Mirrors ServiceRenderedOrder's tender fields so the
    # cash-flow buckets can sum both kinds of job the same way. There is no
    # loyalty/subscription tender here — those need a registered Customer, and a
    # non-catalogue job only carries a free-text contact.
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ('cash', 'Cash'),
            ('momo', 'MoMo'),
            ('card', 'Card'),
            ('split', 'Split'),
        ],
        null=True, blank=True,
    )
    cash_paid = models.FloatField(null=True, blank=True, default=0.0)
    momo_amount = models.FloatField(null=True, blank=True, default=0.0)
    card_amount = models.FloatField(null=True, blank=True, default=0.0)

    # Commission. A non-catalogue job has no Service to inherit a rate from, so
    # the rate is set per job. Defaults to 0 so existing rows stay uncommissioned.
    commission_rate = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Percent of the amount shared among the service-provider workers on this job.",
    )
    commission_amount = models.FloatField(
        null=True, blank=True,
        help_text="Cached commission pool; maintained by allocate_commission().",
    )

    # audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def display_date(self):
        return self.created_at

    @property
    def record_type(self):
        return "other"

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.service_name} ({self.get_status_display()}) – GHS{self.amount:.2f}"

    # ---- payment ---------------------------------------------------------
    @property
    def amount_paid(self):
        """What was actually tendered across all three methods."""
        return (self.cash_paid or 0.0) + (self.momo_amount or 0.0) + (self.card_amount or 0.0)

    @property
    def display_reference(self):
        """Other services have no order number; give reports something stable."""
        return f"OS-{self.pk}"

    def infer_payment_method(self):
        """
        Derive `payment_method` from whichever tender fields carry money, so a
        caller only has to fill in the amounts.
        """
        used = [
            name for name, value in (
                ("cash", self.cash_paid), ("momo", self.momo_amount), ("card", self.card_amount)
            ) if (value or 0) > 0
        ]
        if not used:
            return None
        return "split" if len(used) > 1 else used[0]

    # ---- commission ------------------------------------------------------
    # Mirrors ServiceRendered so callers can treat the two the same way.
    EARNING_STATUSES = ("completed", "onCredit")

    def get_effective_price(self):
        return self.amount or 0.0

    def allocate_commission(self, discount_factor=1):
        allocate_other_service_commission(self, discount_factor=discount_factor)

    def remove_commission(self):
        Commission.objects.filter(other_service=self).delete()
        self.commission_amount = 0.0
        type(self).objects.filter(pk=self.pk).update(commission_amount=0.0)

    def sync_commission(self):
        """
        Bring commission in line with the job's current status, amount, rate and
        worker list. A job only earns once it's completed or on credit; anything
        else clears the rows. Called from signals, so it stays right no matter
        which view moved the job.
        """
        if self.status in self.EARNING_STATUSES:
            self.allocate_commission()
        else:
            self.remove_commission()

    # helpers
    def mark_completed(self, when=None):
        self.status = "completed"
        self.save(update_fields=["status", "updated_at"])

    def mark_canceled(self):
        self.status = "canceled"
        self.save(update_fields=["status", "updated_at"])

    def mark_on_credit(self):
        self.status = "onCredit"
        self.save(update_fields=["status", "updated_at"])


class MaintenanceLog(models.Model):
    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_RESOLVED = "resolved"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CANCELED, "Canceled"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_MED = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MED, "Medium"),
        (PRIORITY_HIGH, "High"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="maintenance_logs")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MED)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)

    reported_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_reported"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.branch.name}] {self.title}"

    @property
    def total_spend(self):
        """Sum of all linked expense items."""
        return self.expenses.aggregate(s=models.Sum("amount"))["s"] or 0.0

    @transaction.atomic
    def mark_resolved(self, when=None):
        if self.status != self.STATUS_RESOLVED:
            self.status = self.STATUS_RESOLVED
            self.resolved_at = when or timezone.now()
            self.save(update_fields=["status", "resolved_at", "updated_at"])


class MaintenanceExpense(models.Model):
    maintenance = models.ForeignKey(MaintenanceLog, on_delete=models.CASCADE, related_name="expenses")
    amount = models.FloatField(validators=[MinValueValidator(0.0)])
    note = models.CharField(max_length=255, blank=True, default="")
    added_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"GHS {self.amount:.2f} – {self.note or 'Expense'}"


# ---------------------------------------------------------------------
# SCORECARD: daily employee performance scoring
# ---------------------------------------------------------------------
class ScorecardCategory(models.Model):
    """Top-level scorecard category. Weights across active categories should sum to 1.0."""
    name = models.CharField(max_length=100, unique=True)
    weight = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Fraction of the final score this category contributes (0.0 – 1.0).",
    )
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = "Scorecard Category"
        verbose_name_plural = "Scorecard Categories"

    def __str__(self):
        return f"{self.name} ({self.weight:.0%})"


class ScorecardCriterion(models.Model):
    """A sub-criterion under a category. Workers start each day at full max_points."""

    AUTO_SOURCE_NONE = ""
    AUTO_SOURCE_ORDERS = "orders"
    AUTO_SOURCE_SERVICES = "services"
    AUTO_SOURCE_VALUE = "value"
    AUTO_SOURCE_CHOICES = [
        (AUTO_SOURCE_NONE, "Manual (GM adjusts)"),
        (AUTO_SOURCE_ORDERS, "Auto — Orders actual / target"),
        (AUTO_SOURCE_SERVICES, "Auto — Services actual / target"),
        (AUTO_SOURCE_VALUE, "Auto — Value (GHS) actual / target"),
    ]

    category = models.ForeignKey(
        ScorecardCategory, on_delete=models.CASCADE, related_name="criteria"
    )
    name = models.CharField(max_length=100)
    max_points = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0.0)],
        help_text="Full-marks value for this criterion.",
    )
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    auto_source = models.CharField(
        max_length=20, choices=AUTO_SOURCE_CHOICES, blank=True, default=AUTO_SOURCE_NONE,
        help_text="If set, this criterion is auto-computed from actual work vs worker's target.",
    )

    class Meta:
        ordering = ["category__display_order", "display_order", "name"]
        unique_together = ("category", "name")

    def __str__(self):
        return f"{self.category.name} – {self.name}"

    @property
    def is_auto(self) -> bool:
        return bool(self.auto_source)


class DailyScorecard(models.Model):
    """One scorecard per worker per day. Entries default to full marks; GMs deduct where needed."""
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="scorecards")
    date = models.DateField(default=timezone.localdate)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="scorecards")
    final_score = models.FloatField(default=0.0, help_text="Cached weighted score 0.0–1.0.")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("worker", "date")
        ordering = ["-date", "worker__user__last_name"]

    def save(self, *args, **kwargs):
        if self.worker_id and (not self.branch_id or self.branch_id != self.worker.branch_id):
            self.branch = self.worker.branch
        super().save(*args, **kwargs)

    def recalc(self):
        """Recompute final_score from current entries. Returns a value in [0,1]."""
        entries = self.entries.select_related("criterion", "criterion__category").all()
        totals = {}
        for entry in entries:
            cat = entry.criterion.category
            awarded, mx, weight = totals.get(cat.id, (0.0, 0.0, cat.weight))
            totals[cat.id] = (
                awarded + (entry.points_awarded or 0.0),
                mx + (entry.criterion.max_points or 0.0),
                cat.weight,
            )
        score = 0.0
        for awarded, mx, weight in totals.values():
            if mx > 0:
                score += (awarded / mx) * weight
        self.final_score = round(score, 4)
        return self.final_score

    def __str__(self):
        return f"{self.worker} – {self.date} – {self.final_score:.0%}"


class DailyScoreEntry(models.Model):
    """Per-criterion score on a daily scorecard. Starts at criterion.max_points."""
    scorecard = models.ForeignKey(
        DailyScorecard, on_delete=models.CASCADE, related_name="entries"
    )
    criterion = models.ForeignKey(
        ScorecardCriterion, on_delete=models.CASCADE, related_name="entries"
    )
    points_awarded = models.FloatField(default=0.0)
    reason = models.TextField(blank=True, default="")
    adjusted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scorecard_adjustments",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("scorecard", "criterion")
        ordering = ["criterion__category__display_order", "criterion__display_order"]

    def __str__(self):
        return (
            f"{self.scorecard} – {self.criterion.name}: "
            f"{self.points_awarded}/{self.criterion.max_points}"
        )



# ============================================================================
#  Utilities
# ============================================================================

class Utility(models.Model):
    """
    A metered/consumable resource tracked per branch (electricity credit,
    water, generator fuel, ...). Readings are logged daily against this.
    """
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="utilities")
    name = models.CharField(max_length=100)
    unit = models.CharField(
        max_length=30, default="units",
        help_text="Unit the balances are measured in, e.g. units, litres, GHS."
    )
    cost_per_unit = models.FloatField(
        default=1.0,
        help_text="GHS per unit, used to book daily usage as an expense. "
                  "Leave at 1.0 when the balance is already in GHS.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("branch", "name")
        ordering = ["branch__name", "name"]
        verbose_name_plural = "Utilities"

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

    def latest_reading(self, before_date=None):
        """Most recent reading, optionally strictly before `before_date`."""
        qs = self.readings.all()
        if before_date is not None:
            qs = qs.filter(date__lt=before_date)
        return qs.order_by("-date").first()

    def opening_for(self, for_date):
        """
        The opening balance a reading on `for_date` should start with: the
        closing balance of the most recent reading before it. Falls back to
        0.0 when this is the very first reading for the utility.
        """
        prev = self.latest_reading(before_date=for_date)
        return float(prev.closing_balance) if prev else 0.0


class UtilityReading(models.Model):
    """
    One day's movement on a Utility. `opening_balance` is carried forward from
    the previous reading's `closing_balance`, so the rows form a trail.

        usage = opening_balance + purchase - closing_balance
    """
    utility = models.ForeignKey(Utility, on_delete=models.CASCADE, related_name="readings")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="utility_readings")
    date = models.DateField(default=timezone.localdate)

    opening_balance = models.FloatField(default=0.0)
    purchase = models.FloatField(default=0.0)
    closing_balance = models.FloatField(default=0.0)
    usage = models.FloatField(default=0.0, editable=False)

    note = models.TextField(blank=True, default="")
    entered_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="utility_readings",
    )
    # The expense this day's usage was booked as. Kept in sync by sync_expense()
    # and cleaned up by the post_delete signal in signals.py.
    expense = models.OneToOneField(
        "Expense", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="utility_reading",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("utility", "date")
        ordering = ["-date", "utility__name"]

    def compute_usage(self):
        return (
            float(self.opening_balance or 0.0)
            + float(self.purchase or 0.0)
            - float(self.closing_balance or 0.0)
        )

    @property
    def expense_amount(self):
        """Usage costed out in GHS."""
        return round(self.usage * float(self.utility.cost_per_unit or 0.0), 2)

    def save(self, *args, **kwargs):
        # A date handed in as a string ("2026-03-02") stays a string on the
        # instance, which breaks date formatting/comparison downstream.
        if self.date is not None:
            self.date = self._meta.get_field("date").to_python(self.date)
        # branch always follows the utility, so a reading can't drift from it
        if self.utility_id and not self.branch_id:
            self.branch = self.utility.branch
        self.usage = self.compute_usage()
        super().save(*args, **kwargs)
        self.sync_expense()
        # A correction to this row changes what the next day opens with.
        self.propagate_forward()

    def sync_expense(self):
        """
        Once the day is closed out, book the usage as a branch Expense.

        Idempotent: re-saving updates the same Expense rather than stacking a
        new one, and an edit that drops usage to zero removes it again.
        """
        Expense = self.__class__._meta.apps.get_model("autodash_App", "Expense")

        amount = self.expense_amount
        should_exist = self.closing_balance is not None and amount > 0

        if not should_exist:
            if self.expense_id:
                stale_id = self.expense_id
                # Break the link first so SET_NULL doesn't fight the delete.
                type(self).objects.filter(pk=self.pk).update(expense=None)
                self.expense = None
                Expense.objects.filter(pk=stale_id).delete()
            return

        description = (
            f"{self.utility.name} usage for {self.date:%d %b %Y} "
            f"({self.usage:g} {self.utility.unit})"
        )

        if self.expense_id:
            exp = self.expense
            exp.branch = self.branch
            exp.description = description
            exp.amount = amount
            exp.expense_type = Expense.TYPE_OPERATING
            exp.is_auto_generated = True
            exp.save(update_fields=[
                "branch", "description", "amount", "expense_type", "is_auto_generated",
            ])
        else:
            exp = Expense.objects.create(
                branch=self.branch,
                description=description,
                amount=amount,
                expense_category="Variable",
                expense_type=Expense.TYPE_OPERATING,
                is_auto_generated=True,
                user=self.entered_by,
            )
            type(self).objects.filter(pk=self.pk).update(expense=exp)
            self.expense = exp

        # Expense.date is auto_now_add, so it always lands on today. Force it
        # onto the reading's date with an UPDATE, which skips auto_now_add.
        Expense.objects.filter(pk=exp.pk).exclude(date=self.date).update(date=self.date)
        exp.date = self.date  # keep the in-memory copy in step with the row

    def propagate_forward(self):
        """
        Re-point the following reading's opening balance at this row's closing
        balance, and keep going while values actually change. Editing an old
        row therefore repairs the whole trail after it rather than silently
        leaving a gap.
        """
        nxt = (
            UtilityReading.objects
            .filter(utility_id=self.utility_id, date__gt=self.date)
            .order_by("date")
            .first()
        )
        current = self
        while nxt is not None:
            new_opening = float(current.closing_balance or 0.0)
            if float(nxt.opening_balance or 0.0) == new_opening:
                break
            nxt.opening_balance = new_opening
            nxt.usage = nxt.compute_usage()
            super(UtilityReading, nxt).save(update_fields=["opening_balance", "usage", "updated_at"])
            # its usage moved, so its expense has to move with it
            nxt.sync_expense()
            current = nxt
            nxt = (
                UtilityReading.objects
                .filter(utility_id=self.utility_id, date__gt=current.date)
                .order_by("date")
                .first()
            )

    def __str__(self):
        return f"{self.utility.name} {self.date}: used {self.usage:g} {self.utility.unit}"


# ============================================================================
#  Remittance
# ============================================================================

def compute_sales_figures(branch=None, start=None, end=None):
    """
    The single definition of the sales chain, shared by the admin dashboard and
    the remittance pages so the two can never drift apart.

        gross sales = revenue - commission
        net sales   = gross sales - operating expenses

    `branch=None` aggregates across all branches. Returns plain floats.
    """
    branch_kw = {'branch': branch} if branch else {}
    worker_branch_kw = {'worker__branch': branch} if branch else {}
    window = {'date__range': [start, end]}

    revenue = Revenue.objects.filter(**window, **branch_kw).aggregate(
        t=Sum('final_amount'))['t'] or 0.0
    commission = Commission.objects.filter(**window, **worker_branch_kw).aggregate(
        t=Sum('amount'))['t'] or 0.0
    expenses_all = Expense.objects.filter(**window, **branch_kw).aggregate(
        t=Sum('amount'))['t'] or 0.0
    operating = Expense.objects.filter(
        expense_type=Expense.TYPE_OPERATING, **window, **branch_kw
    ).aggregate(t=Sum('amount'))['t'] or 0.0

    gross_sales = revenue - commission
    return {
        'revenue': revenue,
        'commission': commission,
        'expenses_all': expenses_all,
        'operating_expenses': operating,
        'other_expenses': expenses_all - operating,
        'gross_sales': gross_sales,
        'net_sales': gross_sales - operating,
    }


REMITTANCE_SOURCE_CASH = "cash"
REMITTANCE_SOURCE_MOMO = "momo"
REMITTANCE_SOURCE_BANK = "bank"
REMITTANCE_SOURCE_CHOICES = (
    (REMITTANCE_SOURCE_CASH, "Cash"),
    (REMITTANCE_SOURCE_MOMO, "MoMo"),
    (REMITTANCE_SOURCE_BANK, "Bank"),
)


class RemittanceSetup(models.Model):
    """
    Per-branch remittance configuration: how much they are expected to remit on
    a given weekday, and which source a surplus defaults into.
    """
    branch = models.OneToOneField(
        Branch, on_delete=models.CASCADE, related_name="remittance_setup"
    )
    target_amount = models.FloatField(
        default=0.0, help_text="Baseline amount expected to be remitted each operating day."
    )
    apply_on = models.JSONField(
        default=list, blank=True,
        help_text="Weekdays this target applies (0=Mon … 6=Sun). Empty means every day.",
    )
    primary_source = models.CharField(
        max_length=10, choices=REMITTANCE_SOURCE_CHOICES, default=REMITTANCE_SOURCE_CASH,
        help_text="Where the target portion is remitted by default. Always editable on the day.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch__name"]

    def applies_on(self, d=None):
        d = d or timezone.localdate()
        if not self.apply_on:
            return True
        return d.weekday() in self.apply_on

    def __str__(self):
        return f"{self.branch.name} — remit GHS {self.target_amount}/day"


class DailyRemittance(models.Model):
    """
    One row per branch per day. Net sales is what *should* be handed over;
    total due is the target plus anything unremitted from previous days.

        total_due   = target_amount + brought_forward
        outstanding = max(0, total_due - amount_remitted)
        surplus     = max(0, net_sales - target_amount)   # flagged, never carried
    """
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="remittances")
    date = models.DateField(default=timezone.localdate)

    target_amount = models.FloatField(default=0.0)
    brought_forward = models.FloatField(
        default=0.0, help_text="Unremitted balance carried in from previous days."
    )
    total_due = models.FloatField(default=0.0, editable=False)

    net_sales = models.FloatField(
        default=0.0, help_text="Recomputed through the day; frozen once the day is finalised."
    )
    is_finalized = models.BooleanField(
        default=False, help_text="Set at day rollover; stops net sales from moving."
    )

    amount_remitted = models.FloatField(default=0.0, editable=False)
    surplus = models.FloatField(default=0.0, editable=False)
    is_settled = models.BooleanField(default=False, editable=False)

    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("branch", "date")
        ordering = ["-date", "branch__name"]

    # ---- derived helpers -------------------------------------------------
    @property
    def outstanding(self):
        return max(0.0, (self.total_due or 0.0) - (self.amount_remitted or 0.0))

    @property
    def shortfall_vs_target(self):
        """How far net sales fell short of the target (0 when met or beaten)."""
        return max(0.0, (self.target_amount or 0.0) - (self.net_sales or 0.0))

    @property
    def progress_pct(self):
        if not self.total_due:
            return 100.0 if self.amount_remitted else 0.0
        return min(100.0, round((self.amount_remitted / self.total_due) * 100, 1))

    def refresh_net_sales(self, commit=False):
        """Pull the live net-sales figure unless the day has been finalised."""
        if self.is_finalized:
            return self.net_sales
        figures = compute_sales_figures(self.branch, self.date, self.date)
        self.net_sales = figures['net_sales']
        if commit:
            self.save()
        return self.net_sales

    def recalc(self, commit=True):
        self.total_due = (self.target_amount or 0.0) + (self.brought_forward or 0.0)
        self.amount_remitted = self.payments.aggregate(t=Sum('amount'))['t'] or 0.0
        # Surplus is measured against the target, per the day's own performance,
        # and is deliberately never carried into tomorrow.
        self.surplus = max(0.0, (self.net_sales or 0.0) - (self.target_amount or 0.0))
        self.is_settled = self.amount_remitted >= self.total_due - 1e-9
        if commit:
            super().save()
        return self

    def carry_to_next_day(self):
        """
        What rolls into tomorrow: due minus what was actually handed over.
        Floored at zero so a surplus never becomes tomorrow's credit.
        """
        return max(0.0, (self.total_due or 0.0) - (self.amount_remitted or 0.0))

    def suggested_split(self):
        """
        Prefill for the payment form: the target goes to the branch's primary
        source, the remainder (surplus) on a second line. Both editable.
        """
        setup = getattr(self.branch, "remittance_setup", None)
        primary = setup.primary_source if setup else REMITTANCE_SOURCE_CASH
        expected = self.net_sales or 0.0
        target = min(self.target_amount or 0.0, expected)
        remainder = round(expected - target, 2)
        rows = []
        if target > 0:
            rows.append({"source": primary, "amount": round(target, 2), "label": "Target"})
        if remainder > 0:
            rows.append({"source": primary, "amount": remainder, "label": "Surplus"})
        if not rows and expected > 0:
            rows.append({"source": primary, "amount": round(expected, 2), "label": "Net sales"})
        return rows

    def save(self, *args, **kwargs):
        if self.date is not None:
            self.date = self._meta.get_field("date").to_python(self.date)
        self.total_due = (self.target_amount or 0.0) + (self.brought_forward or 0.0)
        self.surplus = max(0.0, (self.net_sales or 0.0) - (self.target_amount or 0.0))
        self.is_settled = (self.amount_remitted or 0.0) >= self.total_due - 1e-9
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.branch.name} remittance {self.date}: {self.amount_remitted}/{self.total_due}"


class RemittancePayment(models.Model):
    """A single line of a (possibly split) remittance. Freely editable."""
    remittance = models.ForeignKey(
        DailyRemittance, on_delete=models.CASCADE, related_name="payments"
    )
    source = models.CharField(max_length=10, choices=REMITTANCE_SOURCE_CHOICES)
    amount = models.FloatField(default=0.0)
    reference = models.CharField(
        max_length=120, blank=True, default="",
        help_text="Optional: teller/transaction reference.",
    )
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="remittance_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.remittance.recalc()

    def delete(self, *args, **kwargs):
        remittance = self.remittance
        super().delete(*args, **kwargs)
        remittance.recalc()

    def __str__(self):
        return f"{self.get_source_display()} {self.amount} — {self.remittance}"


def worked_days_map(start, end, branch=None):
    """
    {worker_id: set of dates they worked} between two dates (inclusive).

    Callers that need to combine this with another notion of "on duty" (e.g.
    days a worker was scored) union the sets, so a day counted twice still
    counts once.
    """
    counts = _worked_pairs(start, end, branch)
    days = {}
    for worker_id, day in counts:
        days.setdefault(worker_id, set()).add(day)
    return days


def worked_days_by_worker(start, end, branch=None):
    """
    {worker_id: number of distinct days that worker actually worked} between
    two dates (inclusive). "Worked" means they appear on a service order or on
    an "other service" that day.

    Targets are aggregated off this rather than off the length of the period,
    so someone who worked 3 days of a 30-day month is measured against 3 days
    of target — not 30.
    """
    counts = {}
    for worker_id, _day in _worked_pairs(start, end, branch):
        counts[worker_id] = counts.get(worker_id, 0) + 1
    return counts


def _worked_pairs(start, end, branch=None):
    """Deduped (worker_id, date) pairs for work done in the period."""
    order_qs = ServiceRenderedOrder.objects.filter(date__date__range=[start, end])
    other_qs = OtherService.objects.filter(created_at__date__range=[start, end])
    if branch is not None:
        order_qs = order_qs.filter(branch=branch)
        other_qs = other_qs.filter(branch=branch)

    # Deduped in a set, so several orders on the same day still count as one
    # day worked.
    pairs = set()
    for worker_id, day in (order_qs
                           .annotate(_day=TruncDate('date'))
                           .values_list('workers__id', '_day')):
        if worker_id is not None and day is not None:
            pairs.add((worker_id, day))
    for worker_id, day in (other_qs
                           .annotate(_day=TruncDate('created_at'))
                           .values_list('workers__id', '_day')):
        if worker_id is not None and day is not None:
            pairs.add((worker_id, day))
    return pairs


def worked_worker_ids(start, end, branch=None):
    """IDs of workers who did any work in the period."""
    return set(worked_days_by_worker(start, end, branch).keys())


# ============================================================================
#  Petty cash
# ============================================================================

class PettyCashAccount(models.Model):
    """
    The physical cash float a branch keeps for day-to-day expenses.

    Two models are needed rather than one: this holds the per-branch settings
    (the threshold, whether the float is in use) and a cached balance, while
    `PettyCashTransaction` is the movement log. A ledger alone has nowhere to
    put the threshold; a settings row alone has no audit trail.

    `balance` is a cache — `recalculate()` rebuilds it, and the running
    `balance_after` on each movement, from the transactions themselves. The
    transactions are the truth.
    """
    branch = models.OneToOneField(
        Branch, on_delete=models.CASCADE, related_name="petty_cash"
    )
    low_threshold = models.FloatField(
        default=0.0,
        help_text="Warn once the float falls to or below this. e.g. hold GHS 100, "
                  "warn at GHS 20.",
    )
    balance = models.FloatField(
        default=0.0, editable=False,
        help_text="Cached float balance; rebuilt by recalculate().",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__name"]
        verbose_name = "Petty cash account"
        verbose_name_plural = "Petty cash accounts"

    def __str__(self):
        return f"{self.branch.name} petty cash: GHS {self.balance:.2f}"

    # ---- state ----------------------------------------------------------
    @property
    def is_overdrawn(self):
        """Spent more than was put down. Recorded, never blocked."""
        return self.balance < 0

    @property
    def is_below_threshold(self):
        return self.balance <= self.low_threshold

    @property
    def needs_topup(self):
        return self.is_below_threshold or self.is_overdrawn

    @property
    def shortfall(self):
        """How much a top-up needs to clear the threshold again."""
        return max(0.0, self.low_threshold - self.balance)

    @property
    def status(self):
        if self.is_overdrawn:
            return "overdrawn"
        if self.is_below_threshold:
            return "low"
        return "ok"

    # ---- maintenance ----------------------------------------------------
    def recalculate(self, commit=True):
        """
        Rebuild the running balance from the movements, oldest first, and stamp
        each one's `balance_after`. Cheap at petty-cash volumes and it means a
        back-dated or corrected entry repairs the whole trail after it.
        """
        running = 0.0
        for txn in self.transactions.order_by("date", "id"):
            running = round(running + txn.signed_amount, 2)
            if txn.balance_after != running:
                PettyCashTransaction.objects.filter(pk=txn.pk).update(balance_after=running)
        self.balance = running
        if commit:
            type(self).objects.filter(pk=self.pk).update(balance=running)
        return running

    @classmethod
    def for_branch(cls, branch, create=False):
        """The branch's float, or None. `create=True` opens one on first use."""
        if branch is None:
            return None
        if create:
            account, _ = cls.objects.get_or_create(branch=branch)
            return account
        return cls.objects.filter(branch=branch).first()


class PettyCashTransaction(models.Model):
    """
    One movement of the float: cash put in, or cash spent on an expense.

    `amount` is always the positive figure a person would write down;
    `signed_amount` carries the direction so balances are a plain SUM.
    """
    KIND_TOPUP = "topup"
    KIND_EXPENSE = "expense"
    KIND_ADJUSTMENT = "adjustment"
    KIND_CHOICES = (
        (KIND_TOPUP, "Top-up"),
        (KIND_EXPENSE, "Expense"),
        (KIND_ADJUSTMENT, "Adjustment"),
    )
    # Which way each kind moves the float. An adjustment can go either way, so
    # it carries its own sign in `direction`.
    OUTFLOW_KINDS = (KIND_EXPENSE,)

    account = models.ForeignKey(
        PettyCashAccount, on_delete=models.CASCADE, related_name="transactions"
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name="petty_cash_transactions"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.FloatField(
        validators=[MinValueValidator(0.0)],
        help_text="Positive figure. The kind decides whether it goes in or out.",
    )
    direction = models.SmallIntegerField(
        default=1,
        help_text="+1 money in, -1 money out. Only meaningful for adjustments; "
                  "top-ups and expenses set it from their kind.",
    )
    signed_amount = models.FloatField(default=0.0, editable=False)
    balance_after = models.FloatField(
        default=0.0, editable=False,
        help_text="Float balance immediately after this movement.",
    )

    # An expense-kind movement is the cash side of exactly one Expense row.
    expense = models.OneToOneField(
        "Expense", on_delete=models.CASCADE, null=True, blank=True,
        related_name="petty_cash_transaction",
    )

    date = models.DateField(default=timezone.localdate)
    note = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="petty_cash_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "Petty cash movement"
        verbose_name_plural = "Petty cash movements"
        constraints = [
            models.CheckConstraint(
                condition=Q(direction=1) | Q(direction=-1),
                name="petty_cash_direction_is_plus_or_minus_one",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} GHS {self.amount:.2f} — {self.branch.name} {self.date}"

    @property
    def description(self):
        """What the movement was for, for the ledger view."""
        if self.expense_id:
            return self.expense.description
        return self.note or self.get_kind_display()

    def resolve_direction(self):
        if self.kind in self.OUTFLOW_KINDS:
            return -1
        if self.kind == self.KIND_TOPUP:
            return 1
        # Adjustment: whatever it was given.
        return -1 if self.direction < 0 else 1

    def save(self, *args, **kwargs):
        if self.date is not None:
            self.date = self._meta.get_field("date").to_python(self.date)
        if self.account_id and not self.branch_id:
            self.branch = self.account.branch
        self.direction = self.resolve_direction()
        self.amount = abs(self.amount or 0.0)
        self.signed_amount = round(self.direction * self.amount, 2)
        super().save(*args, **kwargs)
        # The trail after this row moves with it.
        self.account.recalculate()

    def delete(self, *args, **kwargs):
        account = self.account
        super().delete(*args, **kwargs)
        account.recalculate()
