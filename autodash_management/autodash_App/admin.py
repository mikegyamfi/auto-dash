# admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from . import models


# -------------------------------------
# Inlines
# -------------------------------------

class WorkerInline(admin.StackedInline):
    model = models.Worker
    can_delete = False
    verbose_name_plural = 'Worker Profile'
    fk_name = 'user'


class CustomerInline(admin.StackedInline):
    model = models.Customer
    can_delete = False
    verbose_name_plural = 'Customer Profile'
    fk_name = 'user'


class AdminAccountInline(admin.StackedInline):
    model = models.AdminAccount
    can_delete = False
    verbose_name_plural = 'Admin Profile'
    fk_name = 'user'


class ProductPurchasedInline(admin.TabularInline):
    model = models.ProductPurchased
    extra = 0
    fields = ('product', 'quantity', 'total_price')
    readonly_fields = ('total_price',)
    can_delete = False


class ServiceRenderedInline(admin.TabularInline):
    model = models.ServiceRendered
    extra = 0
    fields = ('service', 'commission_amount')
    readonly_fields = ('commission_amount',)
    can_delete = False


class WorkerInlineBranch(admin.TabularInline):
    model = models.Worker
    extra = 0
    fields = ('user', 'position', 'salary', 'is_branch_head', 'daily_commission')
    readonly_fields = ('daily_commission',)
    can_delete = False


# -------------------------------------
# CustomUser Admin
# -------------------------------------

class CustomUserAdmin(UserAdmin):
    model = models.CustomUser
    list_display = ('username', 'email', 'first_name', 'last_name', 'phone_number', 'role', 'is_staff', 'approved')
    list_filter = ('role', 'is_staff', 'approved')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone_number')
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
        (_('Additional Info'), {'fields': ('role', 'approved')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'phone_number', 'email', 'password1', 'password2', 'role', 'approved'),
        }),
    )

    inlines = [WorkerInline, CustomerInline, AdminAccountInline]

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        inlines = []
        if obj.role.lower() == 'worker':
            inlines.append(WorkerInline(self.model, self.admin_site))
        elif obj.role.lower() == 'customer':
            inlines.append(CustomerInline(self.model, self.admin_site))
        elif obj.role.lower() == 'admin':
            inlines.append(AdminAccountInline(self.model, self.admin_site))
        return inlines


admin.site.register(models.CustomUser, CustomUserAdmin)


# -------------------------------------
# Branch Admin
# -------------------------------------

@admin.register(models.Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'phone_number', 'email', 'head_of_branch', 'date_opened')
    search_fields = ('name', 'location', 'head_of_branch', 'email')
    list_filter = ('date_opened',)
    inlines = [WorkerInlineBranch]


# -------------------------------------
# VehicleGroup Admin
# -------------------------------------

@admin.register(models.VehicleGroup)
class VehicleGroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'description')
    search_fields = ('group_name', 'description')
    filter_horizontal = ('branches',)


# -------------------------------------
# Subscription Admin
# -------------------------------------

@admin.register(models.Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'duration_in_days')
    search_fields = ('name',)
    list_filter = ('duration_in_days',)
    filter_horizontal = ('services', 'vehicle_group')


# -------------------------------------
# Service Admin
# -------------------------------------

@admin.register(models.Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'service_type', 'vehicle_group', 'price', 'active', 'loyalty_points_earned', 'loyalty_points_required',
        'commission_rate')
    search_fields = ('service_type', 'vehicle_group__group_name')
    list_filter = ('active', 'vehicle_group')
    # filter_horizontal = ('branches', 'subscriptions')


# -------------------------------------
# ServiceRenderedOrder Admin
# -------------------------------------

@admin.register(models.ServiceRenderedOrder)
class ServiceRenderedOrderAdmin(admin.ModelAdmin):
    list_display = (
        'service_order_number', 'customer', 'branch', 'status', 'total_amount', 'final_amount', 'payment_method',
        'date')
    search_fields = ('service_order_number', 'customer__user__first_name', 'customer__user__last_name', 'branch__name')
    list_filter = ('status', 'payment_method', 'branch', 'date')
    readonly_fields = ('service_order_number',)
    inlines = [ServiceRenderedInline, ProductPurchasedInline]

    actions = ['mark_as_completed']

    def mark_as_completed(self, request, queryset):
        updated = queryset.update(status='completed')
        self.message_user(request, f"{updated} service(s) marked as completed.")

    mark_as_completed.short_description = "Mark selected services as completed"


# -------------------------------------
# ServiceRendered Admin
# -------------------------------------

@admin.register(models.ServiceRendered)
class ServiceRenderedAdmin(admin.ModelAdmin):
    list_display = ('order', 'service', 'date', 'commission_amount')
    search_fields = (
        'order__service_order_number', 'service__service_type', 'workers__user__first_name', 'workers__user__last_name')
    list_filter = ('service', 'date', 'workers')
    filter_horizontal = ('workers',)


# -------------------------------------
# Commission Admin
# -------------------------------------

@admin.register(models.Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ('worker', 'service_rendered', 'amount', 'date')
    search_fields = ('worker__user__first_name', 'worker__user__last_name', 'service_rendered__service_order_number')
    list_filter = ('date', 'worker')


# -------------------------------------
# Expense Admin
# -------------------------------------

@admin.register(models.Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('branch', 'description', 'amount', 'date', 'user')
    search_fields = ('branch__name', 'description', 'user__username')
    list_filter = ('branch', 'date')


# -------------------------------------
# DailyExpenseBudget Admin
# -------------------------------------

@admin.register(models.DailyExpenseBudget)
class DailyExpenseBudgetAdmin(admin.ModelAdmin):
    list_display = ('branch', 'date', 'budgeted_amount')
    search_fields = ('branch__name',)
    list_filter = ('branch', 'date')


# -------------------------------------
# Revenue Admin
# -------------------------------------

@admin.register(models.Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ('service_rendered', 'branch', 'amount', 'discount', 'final_amount', 'profit', 'date', 'user')
    search_fields = ('service_rendered__service_order_number', 'branch__name', 'user__username')
    list_filter = ('branch', 'date', 'user')


# -------------------------------------
# Product Admin
# -------------------------------------

@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'branch', 'stock', 'stock_value')
    search_fields = ('name', 'branch__name')
    list_filter = ('branch',)
    readonly_fields = ('stock_value',)

    def stock_value(self, obj):
        return obj.price * obj.stock

    stock_value.short_description = 'Total Stock Value'


# -------------------------------------
# ProductPurchased Admin
# -------------------------------------

@admin.register(models.ProductPurchased)
class ProductPurchasedAdmin(admin.ModelAdmin):
    list_display = ('service_order', 'product', 'quantity', 'total_price')
    search_fields = ('service_order__service_order_number', 'product__name')
    list_filter = ('product', 'service_order__branch')


# -------------------------------------
# CustomerSubscription Admin
# -------------------------------------

@admin.register(models.CustomerSubscription)
class CustomerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'subscription', 'start_date', 'end_date', 'branch')
    search_fields = ('customer__user__username', 'subscription__name', 'branch__name')
    list_filter = ('subscription', 'branch', 'start_date', 'end_date')


# -------------------------------------
# CustomerVehicle Admin
# -------------------------------------

@admin.register(models.CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = ('customer', 'vehicle_group', 'car_plate', 'car_make', 'car_color', 'date_added')
    search_fields = ('customer__user__username', 'vehicle_group__group_name', 'car_plate', 'car_make', 'car_color')
    list_filter = ('vehicle_group', 'date_added')


# -------------------------------------
# LoyaltyTransaction Admin
# -------------------------------------

@admin.register(models.LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'points', 'transaction_type', 'description', 'branch', 'date')
    search_fields = ('customer__user__username', 'description', 'branch__name')
    list_filter = ('transaction_type', 'branch', 'date')


# -------------------------------------
# Customer Admin (Optional)
# -------------------------------------

@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_joined_app', 'branch', 'loyalty_points')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'branch__name')
    list_filter = ('branch', 'date_joined_app')
