from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Branch, Worker, VehicleGroup, AdminAccount, Subscription,
    CustomerSubscription, Customer, CustomerVehicle, LoyaltyTransaction,
    Service, ServiceRenderedOrder, ServiceRendered, Commission, Expense,
    DailyExpenseBudget, Revenue, Product, ProductPurchased, ProductSale
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # Fields to display and edit in the admin
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Role & Approval', {'fields': ('role', 'approved')}),
    )

    # Fields to show in the user list view
    list_display = ('username', 'first_name', 'last_name', 'role', 'phone_number', 'approved', 'is_staff', 'is_active')
    list_filter = ('role', 'approved', 'is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone_number')

    # Custom action to approve selected users
    actions = ['approve_selected_users']

    def approve_selected_users(self, request, queryset):
        """Approve selected users by setting their 'approved' field to True."""
        updated = queryset.update(approved=True)
        self.message_user(request, f"{updated} user(s) have been approved.")

    approve_selected_users.short_description = "Approve selected users"


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('user', 'branch', 'position', 'is_gh_card_approved', 'is_phone_number_approved', 'is_branch_head')
    list_filter = ('branch', 'is_gh_card_approved', 'is_phone_number_approved', 'is_branch_head')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'position')


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'phone_number', 'head_of_branch', 'email', 'date_opened')
    search_fields = ('name', 'location', 'head_of_branch', 'email')


@admin.register(VehicleGroup)
class VehicleGroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'description')
    search_fields = ('group_name', 'description')


@admin.register(AdminAccount)
class AdminAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'daily_expense_amount')
    search_fields = ('user__username',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'duration_in_days')
    search_fields = ('name', 'amount')
    filter_horizontal = ('services', 'vehicle_group')


@admin.register(CustomerSubscription)
class CustomerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'subscription', 'start_date', 'end_date', 'branch')
    search_fields = ('customer__user__username', 'subscription__name')
    list_filter = ('branch', 'start_date', 'end_date')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_joined_app', 'branch', 'loyalty_points')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    list_filter = ('branch', 'date_joined_app')


@admin.register(CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = ('customer', 'car_plate', 'car_make', 'car_color', 'date_added')
    search_fields = ('customer__user__username', 'car_plate', 'car_make', 'car_color')


@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'points', 'transaction_type', 'branch', 'date')
    search_fields = ('customer__user__username', 'transaction_type', 'description')
    list_filter = ('transaction_type', 'branch', 'date')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'service_type', 'price', 'active', 'loyalty_points_earned', 'loyalty_points_required', 'commission_rate')
    search_fields = ('service_type', 'description')
    list_filter = ('active', 'branches')


@admin.register(ServiceRenderedOrder)
class ServiceRenderedOrderAdmin(admin.ModelAdmin):
    list_display = ('service_order_number', 'customer', 'status', 'total_amount', 'final_amount', 'branch', 'date')
    search_fields = ('service_order_number', 'customer__user__username')
    list_filter = ('status', 'branch', 'date')


@admin.register(ServiceRendered)
class ServiceRenderedAdmin(admin.ModelAdmin):
    list_display = ('order', 'service', 'date', 'commission_amount')
    search_fields = ('order__service_order_number', 'service__service_type')
    list_filter = ('date',)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ('worker', 'service_rendered', 'amount', 'date')
    search_fields = ('worker__user__username', 'service_rendered__order__service_order_number')
    list_filter = ('date',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('branch', 'description', 'amount', 'date', 'user')
    search_fields = ('branch__name', 'description', 'user__username')
    list_filter = ('date', 'branch')


@admin.register(DailyExpenseBudget)
class DailyExpenseBudgetAdmin(admin.ModelAdmin):
    list_display = ('branch', 'date', 'budgeted_amount')
    search_fields = ('branch__name',)
    list_filter = ('date',)


@admin.register(Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ('branch', 'amount', 'final_amount', 'profit', 'date')
    search_fields = ('branch__name',)
    list_filter = ('date',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'branch', 'stock')
    search_fields = ('name', 'branch__name')
    list_filter = ('branch',)


@admin.register(ProductPurchased)
class ProductPurchasedAdmin(admin.ModelAdmin):
    list_display = ('service_order', 'product', 'quantity', 'total_price')
    search_fields = ('service_order__service_order_number', 'product__name')


# After this setup:
# - Go to the Django admin site.
# - Look up CustomUsers filtered by role='worker'.
# - Select the workers you want to approve.
# - Use the "Approve selected users" action from the dropdown.
# This will update their 'approved' field to True.
@admin.register(ProductSale)
class ProductSaleAdmin(admin.ModelAdmin):
    ...
