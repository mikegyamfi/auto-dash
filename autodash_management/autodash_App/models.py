from django.db import models
from django.contrib.auth.models import AbstractUser
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
    head_of_branch = models.CharField(max_length=100)
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


class VehicleGroup(models.Model):
    group_name = models.CharField(max_length=100, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    branches = models.ManyToManyField(Branch, related_name='vehiclegroups')

    def __str__(self):
        return f"{self.group_name}"


class AdminAccount(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='admin_profile')


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
    # user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='vehicle_profile')
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='vehicles', null=True, blank=True)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='vehicles', null=True, blank=True)
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


# Service Model with Loyalty Points
class Service(models.Model):
    service_type = models.CharField(max_length=100)
    vehicle_group = models.ForeignKey(VehicleGroup, on_delete=models.CASCADE, related_name='services', null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    price = models.FloatField()
    branches = models.ManyToManyField(Branch, related_name='services')
    active = models.BooleanField(default=True)
    loyalty_points_earned = models.IntegerField(default=0)
    loyalty_points_required = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.service_type} - {self.vehicle_group.group_name}"


def generate_unique_order_number():
    prefix = "SRV"  # You can customize this prefix as needed
    order_number = helper.generate_service_order_number(prefix)

    # Check if the generated service order number already exists
    while ServiceRenderedOrder.objects.filter(service_order_number=order_number).exists():
        order_number = helper.generate_service_order_number(prefix)  # Regenerate if it exists

    return order_number


class ServiceRenderedOrder(models.Model):
    service_order_number = models.CharField(max_length=100, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    workers = models.ManyToManyField(Worker, null=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    status = models.CharField(max_length=50,
                              choices=[('completed', 'Completed'), ('pending', 'Pending'), ('canceled', 'Canceled')],
                              default='pending')
    total_amount = models.FloatField()
    amount_paid = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    discount = models.FloatField(null=True, blank=True)
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

    # def save(self, *args, **kwargs):
    #     super().save(*args, **kwargs)
    #     self.customer.add_loyalty_points(self.service.loyalty_points_earned,
    #                                      description=f"Loyalty points for {self.service.service_type}")
    #     self.customer.save()
    #
    # def apply_loyalty_or_subscription(self):
    #     if self.customer.can_redeem_service(self.service):
    #         self.payment_method = 'loyalty'
    #         self.customer.apply_loyalty(self.service.loyalty_points_required,
    #                                     description=f"Redeemed for {self.service.service_type}")
    #     elif CustomerSubscription.objects.filter(customer=self.customer, subscription__services=self.service,
    #                                              end_date__gte=timezone.now()).exists():
    #         self.payment_method = 'subscription'
    #     else:
    #         self.payment_method = 'cash'
    #     self.save()

    def save(self, *args, **kwargs):
        if not self.service_order_number:
            self.service_order_number = generate_unique_order_number()

        super(ServiceRenderedOrder, self).save(*args, **kwargs)


# Service Rendered Model
class ServiceRendered(models.Model):
    order = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='rendered', null=True,
                              blank=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='services_rendered')
    workers = models.ManyToManyField(Worker, related_name='services_rendered', null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)


# Revenue Model
class Revenue(models.Model):
    service_rendered = models.ForeignKey(ServiceRenderedOrder, on_delete=models.CASCADE, related_name='revenues',
                                         null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='revenues')
    amount = models.FloatField()
    discount = models.FloatField(null=True, blank=True)
    final_amount = models.FloatField(null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='revenues', null=True, blank=True)

    def __str__(self):
        return f"Revenue for {self.branch.name} on {self.date}: {self.amount}"
