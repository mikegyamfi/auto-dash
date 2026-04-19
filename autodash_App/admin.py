from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone

from .models import (
    CustomUser, Branch, Worker, WorkerCategory,
    VehicleGroup, AdminAccount, Subscription,
    CustomerSubscription, Customer, CustomerVehicle,
    LoyaltyTransaction, Service, ServiceCategory,
    ServiceRenderedOrder, ServiceRendered, Commission,
    Expense, DailyExpenseBudget, Revenue, Product,
    ProductCategory, ProductPurchased, ProductSale, RecurringExpense, WeeklyBudget, WorkerReference, WorkerGuarantor,
    WorkerEmployment, WorkerEducation, DailySalesTarget, Arrears, DailyPaymentTarget, RecurringPaymentSetup,
    ScorecardCategory, ScorecardCriterion, DailyScorecard, DailyScoreEntry,
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
    list_display = ('user', 'get_phone_number', 'date_joined_app', 'branch', 'loyalty_points')
    search_fields = (
        'user__username',
        'user__first_name',
        'user__last_name',
        'user__phone_number',
        'user__email'
    )
    list_filter = ('branch', 'customer_group', 'date_joined_app')

    # Register the custom export action
    actions = ['export_customers_to_excel']

    # Custom display method for the list view
    @admin.display(ordering='user__phone_number', description='Phone Number')
    def get_phone_number(self, obj):
        return obj.user.phone_number if obj.user else '-'

    # -------------------------------------------------------------------------
    # EXPORT ACTION
    # -------------------------------------------------------------------------
    @admin.action(description="Export Selected Customers to Excel (CSV)")
    def export_customers_to_excel(self, request, queryset):
        """
        Exports selected customers to a CSV file.
        Uses the ="..." trick to force Excel to treat phone numbers as literal strings.
        """
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="customers_export.csv"'
        writer = csv.writer(response)

        # Write the header row
        writer.writerow([
            'First Name',
            'Last Name',
            'Phone (Raw)',
            'Phone (233)',
            'Phone (0)',
            'Email',
            'Address',
            'Branch',
            'Customer Group',
            'Loyalty Points',
            'Date Joined'
        ])

        # Write data rows
        for customer in queryset:
            first_name = customer.user.first_name if customer.user else '-'
            last_name = customer.user.last_name if customer.user else '-'
            email = customer.user.email if customer.user else '-'
            address = customer.user.address if customer.user else '-'

            # --- Phone Number Logic ---
            raw_phone = customer.user.phone_number if customer.user and customer.user.phone_number else ''

            # Default to dash if no phone exists
            phone_raw_str = '-'
            phone_233 = '-'
            phone_0 = '-'

            if raw_phone:
                # Remove spaces, plus signs, or dashes to safely parse
                clean_num = ''.join(filter(str.isdigit, raw_phone))

                # Strip existing '233' or '0' prefix to isolate the core 9-digit number
                if clean_num.startswith('233'):
                    core_num = clean_num[3:]
                elif clean_num.startswith('0'):
                    core_num = clean_num[1:]
                else:
                    core_num = clean_num

                # Wrap in ="..." to force Excel to treat them strictly as strings
                phone_raw_str = f'="{raw_phone}"'
                phone_233 = f'="233{core_num}"'
                phone_0 = f'="0{core_num}"'

            # Safely extract customer data
            branch_name = customer.branch.name if customer.branch else '-'
            group = customer.customer_group if customer.customer_group else '-'
            date_joined = customer.date_joined_app.strftime("%Y-%m-%d") if customer.date_joined_app else "-"

            writer.writerow([
                first_name,
                last_name,
                phone_raw_str,
                phone_233,
                phone_0,
                email,
                address,
                branch_name,
                group,
                customer.loyalty_points,
                date_joined
            ])

        return response


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
        'status', 'cash_paid', 'total_amount', 'final_amount',
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


import csv
from django.contrib import admin
from django.http import HttpResponse
from django.utils.timezone import localtime

# Safely import reportlab to prevent production 500 errors if it's not installed yet
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# Import your Arrears model here
# from .models import Arrears

@admin.register(Arrears)
class ArrearsAdmin(admin.ModelAdmin):
    # What to show in the list view
    list_display = (
        'get_order_number',
        'get_customer_name',
        'branch',
        'amount_owed',
        'is_paid',
        'date_created',
        'date_paid'
    )

    # Filter sidebar
    list_filter = ('is_paid', 'branch', 'date_created')

    # Search bar (searches order number, customer name, and branch)
    search_fields = (
        'service_order__service_order_number',
        'service_order__customer__user__first_name',
        'service_order__customer__user__last_name',
        'service_order__customer__user__phone_number',
        'branch__name',
    )

    # Date drill-down navigation at the top
    date_hierarchy = 'date_created'
    readonly_fields = ('date_created',)

    # Register our custom actions
    actions = ['export_to_csv_excel', 'export_to_pdf']

    # -------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # -------------------------------------------------------------------------
    @admin.display(ordering='service_order__service_order_number', description='Order Number')
    def get_order_number(self, obj):
        return obj.service_order.service_order_number if obj.service_order else '-'

    @admin.display(ordering='service_order__customer__user__first_name', description='Customer')
    def get_customer_name(self, obj):
        if obj.service_order and obj.service_order.customer and obj.service_order.customer.user:
            user = obj.service_order.customer.user
            return f"{user.first_name} {user.last_name}".strip() or user.username
        return '-'

    # -------------------------------------------------------------------------
    # EXPORT ACTIONS
    # -------------------------------------------------------------------------
    @admin.action(description="Export Selected to Excel (CSV)")
    def export_to_csv_excel(self, request, queryset):
        """
        Exports selected rows to a CSV file that opens natively in Excel.
        Uses pure built-in Python libraries to guarantee no production crashes.
        """
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="arrears_export.csv"'
        writer = csv.writer(response)

        # Write the header row
        writer.writerow([
            'Order Number', 'Customer', 'Branch', 'Amount Owed (GHS)',
            'Paid Status', 'Date Created', 'Date Paid'
        ])

        # Write data rows
        for obj in queryset:
            created = localtime(obj.date_created).strftime("%Y-%m-%d %H:%M") if obj.date_created else ""
            paid = localtime(obj.date_paid).strftime("%Y-%m-%d %H:%M") if obj.date_paid else ""

            writer.writerow([
                self.get_order_number(obj),
                self.get_customer_name(obj),
                obj.branch.name if obj.branch else '-',
                obj.amount_owed,
                'Paid' if obj.is_paid else 'Unpaid',
                created,
                paid
            ])

        return response

    @admin.action(description="Export Selected to PDF")
    def export_to_pdf(self, request, queryset):
        """
        Exports selected rows to a nicely formatted PDF table.
        """
        if not HAS_REPORTLAB:
            self.message_user(
                request,
                "ReportLab is not installed on the server. Please run 'pip install reportlab' to enable PDF exports.",
                level='ERROR'
            )
            return None

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="arrears_export.pdf"'

        # Setup PDF Document in Landscape for better table fitting
        doc = SimpleDocTemplate(response, pagesize=landscape(letter))
        elements = []
        styles = getSampleStyleSheet()

        # Title
        elements.append(Paragraph("Arrears Report Export", styles['Title']))

        # Table Header
        data = [['Order Number', 'Customer', 'Branch', 'Amount (GHS)', 'Status', 'Date Created']]

        # Table Data
        for obj in queryset:
            created = localtime(obj.date_created).strftime("%Y-%m-%d") if obj.date_created else ""
            data.append([
                self.get_order_number(obj),
                self.get_customer_name(obj),
                obj.branch.name if obj.branch else '-',
                f"{obj.amount_owed:.2f}",
                'Paid' if obj.is_paid else 'Unpaid',
                created
            ])

        # Draw and Style the Table nicely
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),  # Dark blue header
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),  # White text for header
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),  # Light grey rows
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),  # Borders
        ]))

        elements.append(table)
        doc.build(elements)

        return response


def force_generate_targets(modeladmin, request, queryset):
    """
    Manually triggers the generation of daily targets for the selected setups.
    """
    today = timezone.localdate()
    generated_count = 0

    for setup in queryset:
        if setup.applies_today(today):
            # Prevent duplicates
            if DailyPaymentTarget.objects.filter(setup=setup, date=today).exists():
                continue

            # Check for rollover debt
            last_target = DailyPaymentTarget.objects.filter(
                setup=setup,
                date__lt=today
            ).order_by('-date').first()

            brought_forward = 0.0
            if last_target:
                # By allowing negative numbers, an overpayment becomes a credit for tomorrow!
                brought_forward = last_target.total_target - last_target.amount_paid

            # Create target
            DailyPaymentTarget.objects.create(
                setup=setup,
                date=today,
                branch=setup.branch,
                base_amount=setup.base_amount,
                brought_forward=brought_forward
            )
            generated_count += 1

    messages.success(request, f"Successfully generated {generated_count} new targets for today.")


force_generate_targets.short_description = "Force generate today's targets for selected setups"


# --- 1. Admin for the Recurring Rules ---
@admin.register(RecurringPaymentSetup)
class RecurringPaymentSetupAdmin(admin.ModelAdmin):
    list_display = ('description', 'branch', 'base_amount', 'display_apply_on')
    list_filter = ('branch',)
    search_fields = ('description', 'branch__name')
    actions = [force_generate_targets]

    def display_apply_on(self, obj):
        """Makes the JSON list of days easier to read in the admin"""
        days = {
            0: "Mon", 1: "Tue", 2: "Wed",
            3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
        }
        active_days = [days.get(day, str(day)) for day in obj.apply_on]
        return ", ".join(active_days)

    display_apply_on.short_description = 'Active Days'


# --- 2. Admin for the Actual Daily Bills ---
@admin.register(DailyPaymentTarget)
class DailyPaymentTargetAdmin(admin.ModelAdmin):
    list_display = (
        'date',
        'setup_description',
        'branch',
        'base_amount',
        'brought_forward',
        'total_target',
        'amount_paid',
        'is_settled'
    )
    # Allows you to type payments directly into the list view without opening the record!
    list_editable = ('amount_paid',)

    list_filter = ('date', 'is_settled', 'branch')
    search_fields = ('setup__description', 'branch__name')
    readonly_fields = ('total_target', 'is_settled')
    date_hierarchy = 'date'

    def setup_description(self, obj):
        return obj.setup.description

    setup_description.short_description = 'Bill / Setup'

    # Optional: Highlight rows that are settled vs unpaid in the admin
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('setup', 'branch')


# ---------------------- Scorecard admin ----------------------
class ScorecardCriterionInline(admin.TabularInline):
    model = ScorecardCriterion
    extra = 1
    fields = ('name', 'max_points', 'display_order', 'active')


@admin.register(ScorecardCategory)
class ScorecardCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'weight', 'display_order', 'active')
    list_editable = ('weight', 'display_order', 'active')
    ordering = ('display_order', 'name')
    inlines = [ScorecardCriterionInline]


@admin.register(ScorecardCriterion)
class ScorecardCriterionAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'max_points', 'display_order', 'active')
    list_filter = ('category', 'active')
    list_editable = ('max_points', 'display_order', 'active')
    search_fields = ('name', 'category__name')


class DailyScoreEntryInline(admin.TabularInline):
    model = DailyScoreEntry
    extra = 0
    readonly_fields = ('criterion', 'adjusted_by', 'updated_at')
    fields = ('criterion', 'points_awarded', 'reason', 'adjusted_by', 'updated_at')


@admin.register(DailyScorecard)
class DailyScorecardAdmin(admin.ModelAdmin):
    list_display = ('worker', 'date', 'branch', 'final_score', 'updated_at')
    list_filter = ('branch', 'date')
    search_fields = ('worker__user__first_name', 'worker__user__last_name')
    date_hierarchy = 'date'
    readonly_fields = ('final_score', 'created_at', 'updated_at', 'branch')
    inlines = [DailyScoreEntryInline]
