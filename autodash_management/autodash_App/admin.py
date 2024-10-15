# admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    CustomUser, Branch, Worker, VehicleGroup, AdminAccount, Subscription,
    CustomerSubscription, Customer, CustomerVehicle, LoyaltyTransaction,
    Service, ServiceRenderedOrder, ServiceRendered, Revenue
)


# Register the CustomUser model using the built-in UserAdmin
class CustomUserAdmin(BaseUserAdmin):
    # Fields to be used in displaying the User model.
    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {'fields': ('role', 'phone_number', 'address', 'approved')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {'fields': ('role', 'phone_number', 'address', 'approved')}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')


admin.site.register(CustomUser, CustomUserAdmin)


# Register Branch
@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'phone_number', 'head_of_branch', 'email', 'date_opened')
    search_fields = ('name', 'location', 'head_of_branch')
    list_filter = ('date_opened',)


# Register Worker
@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('user', 'position', 'branch', 'date_joined', 'average_rating')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'position')
    list_filter = ('branch', 'position', 'date_joined')
    readonly_fields = ('average_rating',)


# Register VehicleGroup
@admin.register(VehicleGroup)
class VehicleGroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'description')
    search_fields = ('group_name',)
    filter_horizontal = ('branches',)


# Register AdminAccount
@admin.register(AdminAccount)
class AdminAccountAdmin(admin.ModelAdmin):
    list_display = ('user',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name')


# Register Subscription
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'duration_in_days')
    search_fields = ('name',)
    filter_horizontal = ('services', 'vehicle_group')


# Register CustomerSubscription
@admin.register(CustomerSubscription)
class CustomerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'subscription', 'start_date', 'end_date', 'is_active')
    search_fields = ('customer__user__username', 'subscription__name')
    list_filter = ('start_date', 'end_date')
    readonly_fields = ('is_active',)

    def is_active(self, obj):
        return obj.is_active()

    is_active.boolean = True
    is_active.short_description = 'Active'


# Register Customer
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'branch', 'loyalty_points', 'date_joined_app')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    list_filter = ('branch', 'date_joined_app')


# Register CustomerVehicle
@admin.register(CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = ('customer', 'vehicle_group', 'car_plate', 'car_make', 'car_color')
    search_fields = ('customer__user__username', 'car_plate', 'car_make', 'car_color')
    list_filter = ('vehicle_group',)


# Register LoyaltyTransaction
@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'points', 'transaction_type', 'date')
    search_fields = ('customer__user__username', 'customer__user__first_name', 'customer__user__last_name')
    list_filter = ('transaction_type', 'date')


# Register Service
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('service_type', 'price', 'active', 'vehicle_group', 'loyalty_points_earned', 'loyalty_points_required')
    search_fields = ('service_type',)
    list_filter = ('active', 'branches', 'vehicle_group')
    filter_horizontal = ('branches',)


# Register ServiceRenderedOrder
@admin.register(ServiceRenderedOrder)
class ServiceRenderedOrderAdmin(admin.ModelAdmin):
    list_display = ('service_order_number', 'customer', 'status', 'total_amount', 'final_amount', 'date')
    search_fields = (
        'service_order_number', 'customer__user__username', 'customer__user__first_name', 'customer__user__last_name')
    list_filter = ('status', 'date', 'branch')
    filter_horizontal = ('workers',)


# Register ServiceRendered
@admin.register(ServiceRendered)
class ServiceRenderedAdmin(admin.ModelAdmin):
    list_display = ('order', 'service', 'date')
    search_fields = ('order__service_order_number', 'service__service_type')
    list_filter = ('date',)
    filter_horizontal = ('workers',)


# Register Revenue
@admin.register(Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ('service_rendered', 'branch', 'amount', 'date')
    search_fields = ('service_rendered__service_order_number', 'branch__name')
    list_filter = ('date', 'branch')
