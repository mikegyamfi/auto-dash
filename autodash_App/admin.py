from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Branch, Worker, WorkerCategory,
    VehicleGroup, AdminAccount, Subscription,
    CustomerSubscription, Customer, CustomerVehicle,
    LoyaltyTransaction, Service, ServiceCategory,
    ServiceRenderedOrder, ServiceRendered, Commission,
    Expense, DailyExpenseBudget, Revenue, Product,
    ProductCategory, ProductPurchased, ProductSale, RecurringExpense, WeeklyBudget, WorkerReference, WorkerGuarantor,
    WorkerEmployment, WorkerEducation, DailySalesTarget
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """CustomUser admin with approval action."""
    fieldsets = (
        (None, {
            'fields': ('username', 'password')
        }),
        ('Personal Info', {
            'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Role & Approval', {
            'fields': ('role', 'approved')
        }),
    )

    list_display = (
        'username', 'first_name', 'last_name', 'role',
        'phone_number', 'approved', 'is_staff', 'is_active'
    )
    list_filter = (
        'role', 'approved', 'is_staff', 'is_superuser',
        'is_active', 'groups'
    )
    search_fields = (
        'username', 'first_name', 'last_name',
        'email', 'phone_number'
    )

    actions = ['approve_selected_users']

    def approve_selected_users(self, request, queryset):
        updated = queryset.update(approved=True)
        self.message_user(
            request,
            f"{updated} user(s) have been approved."
        )

    approve_selected_users.short_description = "Approve selected users"


@admin.register(WorkerCategory)
class WorkerCategoryAdmin(admin.ModelAdmin):
    """Admin for different categories a Worker can have."""
    list_display = ('name', 'service_provider')
    search_fields = ('name', 'description')
    list_filter = ('service_provider',)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'location', 'phone_number',
        'head_of_branch', 'email', 'date_opened'
    )
    search_fields = ('name', 'location', 'head_of_branch', 'email')
    list_filter = ('date_opened',)


@admin.register(VehicleGroup)
class VehicleGroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'description')
    search_fields = ('group_name', 'description')
    # If you want to see branches in the admin form:
    filter_horizontal = ('branches',)


@admin.register(AdminAccount)
class AdminAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'daily_expense_amount')
    search_fields = ('user__username', 'user__email')


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'negotiable')
    list_filter = ('negotiable',)
    search_fields = ('name', 'description')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    """
    Example of referencing a foreign key:
    We'll define a custom method to display the vehicle_group's name.
    """
    list_display = (
        'service_type',
        'price',
        'vehicle_group_name',
        'loyalty_points_earned',
        'loyalty_points_required',
        'commission_rate',
        'active',
    )
    search_fields = ('service_type', 'description')
    list_filter = ('active', 'branches', 'vehicle_group', 'category')
    filter_horizontal = ('branches',)

    def vehicle_group_name(self, obj):
        return obj.vehicle_group.group_name if obj.vehicle_group else ''

    vehicle_group_name.short_description = "Vehicle Group"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'duration_in_days')
    search_fields = ('name', 'description')
    filter_horizontal = ('services', 'vehicle_group')


@admin.register(CustomerSubscription)
class CustomerSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'customer', 'subscription', 'start_date',
        'end_date', 'branch'
    )
    search_fields = (
        'customer__user__username',
        'subscription__name'
    )
    list_filter = ('branch', 'start_date', 'end_date')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_joined_app', 'branch', 'loyalty_points')
    search_fields = (
        'user__username',
        'user__first_name',
        'user__last_name'
    )
    list_filter = ('branch', 'date_joined_app')


@admin.register(CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = (
        'customer', 'vehicle_group',
        'car_plate', 'car_make',
        'car_color', 'date_added'
    )
    search_fields = (
        'customer__user__username',
        'car_plate', 'car_make', 'car_color'
    )
    list_filter = ('vehicle_group', 'date_added')


@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'customer', 'points', 'transaction_type',
        'branch', 'date'
    )
    search_fields = (
        'customer__user__username',
        'transaction_type',
        'description'
    )
    list_filter = ('transaction_type', 'branch', 'date')


@admin.register(ServiceRenderedOrder)
class ServiceRenderedOrderAdmin(admin.ModelAdmin):
    list_display = (
        'service_order_number', 'customer',
        'status', 'total_amount', 'final_amount',
        'branch', 'date'
    )
    search_fields = (
        'service_order_number',
        'customer__user__username'
    )
    list_filter = ('status', 'branch', 'date')


@admin.register(ServiceRendered)
class ServiceRenderedAdmin(admin.ModelAdmin):
    list_display = ('order', 'service', 'date', 'commission_amount')
    search_fields = (
        'order__service_order_number',
        'service__service_type'
    )
    list_filter = ('date', 'service')


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = (
        'worker', 'service_rendered',
        'amount', 'date'
    )
    search_fields = (
        'worker__user__username',
        'service_rendered__order__service_order_number'
    )
    list_filter = ('date', 'worker__branch')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        'branch', 'description', 'amount',
        'date', 'user'
    )
    search_fields = (
        'branch__name', 'description', 'user__username'
    )
    list_filter = ('branch', 'date')


@admin.register(DailyExpenseBudget)
class DailyExpenseBudgetAdmin(admin.ModelAdmin):
    list_display = ('branch', 'date', 'budgeted_amount')
    search_fields = ('branch__name',)
    list_filter = ('date',)


@admin.register(Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ('branch', 'amount', 'final_amount', 'profit', 'date', 'user')
    search_fields = ('branch__name', 'user__username')
    list_filter = ('branch', 'date')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'cost', 'stock')
    search_fields = ('name',)
    list_filter = ('category', 'branch')


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name', 'description')


@admin.register(ProductPurchased)
class ProductPurchasedAdmin(admin.ModelAdmin):
    list_display = ('service_order', 'product', 'quantity', 'total_price')
    search_fields = (
        'service_order__service_order_number',
        'product__name'
    )


@admin.register(ProductSale)
class ProductSaleAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'quantity', 'total_price',
        'branch', 'date_sold'
    )
    search_fields = ('product__name', 'branch__name')
    list_filter = ('branch', 'date_sold')


admin.site.register(RecurringExpense)
admin.site.register(WeeklyBudget)


class WorkerEducationInline(admin.StackedInline):
    model = WorkerEducation
    extra = 1
    verbose_name_plural = "Educational Records"


class WorkerEmploymentInline(admin.StackedInline):
    model = WorkerEmployment
    extra = 1
    verbose_name_plural = "Employment Records"


class WorkerReferenceInline(admin.StackedInline):
    model = WorkerReference
    extra = 1
    verbose_name_plural = "References"


class WorkerGuarantorInline(admin.StackedInline):
    model = WorkerGuarantor
    extra = 1
    verbose_name_plural = "Guarantors"


#
# Worker admin, with all inlines
#
@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'branch',
        'position',
        'is_branch_admin',
        'is_gh_card_approved',
    )
    list_filter = (
        'branch',
        'worker_category',
        'is_branch_admin',
        'is_gh_card_approved',
    )
    search_fields = (
        'user__first_name',
        'user__last_name',
        'user__email',
        'branch__name',
    )
    readonly_fields = (
        'date_joined',
        'rating_sum',
        'rating_count',
        'daily_commission',
    )
    fieldsets = (
        (None, {
            'fields': (
                'user',
                'branch',
                'worker_category',
                'position',
                'salary',
                'is_branch_admin',
            )
        }),
        ('Ghana Card', {
            'fields': (
                'gh_card_number',
                'gh_card_photo',
                'is_gh_card_approved',
            )
        }),
        ('Personal & ID', {
            'fields': (
                'date_of_birth',
                'place_of_birth',
                'nationality',
                'home_address',
                'landmark',
                'ecowas_id_card_no',
                'ecowas_id_card_photo',
                'passport_photo',
            )
        }),
        ('Stats (read-only)', {
            'fields': (
                'date_joined',
                'rating_sum',
                'rating_count',
                'daily_commission',
            )
        }),
    )
    inlines = [
        WorkerEducationInline,
        WorkerEmploymentInline,
        WorkerReferenceInline,
        WorkerGuarantorInline,
    ]


#
# Separate admin for each related model
#
@admin.register(WorkerEducation)
class WorkerEducationAdmin(admin.ModelAdmin):
    list_display = ('worker', 'school_name', 'school_location', 'year_completed')
    list_filter = ('year_completed',)
    search_fields = ('worker__user__first_name', 'school_name')


@admin.register(WorkerEmployment)
class WorkerEmploymentAdmin(admin.ModelAdmin):
    list_display = (
        'worker',
        'employer_name',
        'contact_number',
        'position',
        'last_date_of_work',
    )
    list_filter = ('position',)
    search_fields = ('worker__user__first_name', 'employer_name')


@admin.register(WorkerReference)
class WorkerReferenceAdmin(admin.ModelAdmin):
    list_display = ('worker', 'full_name', 'mobile_number')
    search_fields = ('worker__user__first_name', 'full_name')


@admin.register(WorkerGuarantor)
class WorkerGuarantorAdmin(admin.ModelAdmin):
    list_display = ('worker', 'full_name', 'mobile_number')
    search_fields = ('worker__user__first_name', 'full_name')


@admin.register(DailySalesTarget)
class DailySalesTargetAdmin(admin.ModelAdmin):
    list_display = ('branch','get_weekday_display','target_amount')
    list_editable = ('target_amount',)
    list_filter = ('branch','weekday')







