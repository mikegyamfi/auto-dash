import json

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from autodash_App import models
from autodash_App.models import ServiceRendered, Customer, CustomUser, Service, Worker, Branch, Product, Expense, \
    VehicleGroup, CustomerVehicle, CustomerBooking


class CustomUserForm(UserCreationForm):
    first_name = forms.CharField(widget=forms.TextInput(
        {'class': 'form-control form-control-lg', 'autocomplete': 'off', 'placeholder': 'First Name'}))
    last_name = forms.CharField(
        widget=forms.TextInput(
            {'class': 'form-control form-control-lg', 'autocomplete': 'off', 'placeholder': 'Last Name'}))
    email = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Email'}))
    phone_number = forms.CharField(
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Phone Number'}))
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Password'}))
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Confirm Password'}))

    class Meta:
        model = models.CustomUser
        fields = ['first_name', 'last_name', 'username', 'email', 'phone_number', 'password1', 'password2']


class LogServiceForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'customer-select'}),
        empty_label="Select Customer",
        required=False
    )

    vehicle = forms.ModelChoiceField(
        queryset=models.CustomerVehicle.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'vehicle-select'}),
        empty_label="Select Vehicle",
        required=False
    )

    service = forms.ModelMultipleChoiceField(
        queryset=Service.objects.none(),
        widget=forms.SelectMultiple(attrs={
            'class': 'form-control',
            'placeholder': 'Select services',
            'id': 'service-select',
        }),
    )

    workers = forms.ModelMultipleChoiceField(
        queryset=None,
        label="Select Workers",
        widget=forms.SelectMultiple(attrs={
            'class': 'form-control',
            'placeholder': 'Select Workers',
        }),
    )
    comments = forms.CharField(widget=forms.Textarea(
        attrs={'class': 'form-control', 'placeholder': 'Leave notes or comments on the service been logged'}),
                               required=False)

    products = forms.ModelMultipleChoiceField(queryset=Product.objects.all(), widget=forms.CheckboxSelectMultiple,
                                              required=False)
    product_quantities = forms.CharField(widget=forms.HiddenInput(),
                                         required=False)  # To capture quantities via JavaScript
    negotiated_prices = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, branch, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['workers'].queryset = Worker.objects.filter(branch=branch)
        self.fields['products'].queryset = Product.objects.filter(branch=branch, stock__gt=0)

        # Set vehicle queryset based on customer
        if 'customer' in self.data:
            try:
                customer_id = int(self.data.get('customer'))
                self.fields['vehicle'].queryset = models.CustomerVehicle.objects.filter(customer_id=customer_id)
            except (ValueError, TypeError):
                pass  # Invalid input
        else:
            self.fields['vehicle'].queryset = models.CustomerVehicle.objects.all()

        # Set service queryset based on vehicle
        if 'vehicle' in self.data:
            try:
                vehicle_id = int(self.data.get('vehicle'))
                vehicle = models.CustomerVehicle.objects.get(id=vehicle_id)
                vehicle_group = vehicle.vehicle_group
                self.fields['service'].queryset = Service.objects.filter(vehicle_group=vehicle_group, active=True)
            except (ValueError, TypeError, models.CustomerVehicle.DoesNotExist):
                pass
        elif self.initial.get('vehicle'):
            try:
                vehicle = models.CustomerVehicle.objects.get(id=self.initial.get('vehicle'))
                vehicle_group = vehicle.vehicle_group
                self.fields['service'].queryset = Service.objects.filter(vehicle_group=vehicle_group, active=True)
            except (ValueError, TypeError, models.CustomerVehicle.DoesNotExist):
                pass
        else:
            self.fields['service'].queryset = Service.objects.none()

    def clean_service(self):
        services = self.cleaned_data.get('service')
        if not services:
            raise forms.ValidationError("Please select at least one service.")
        return services

    def clean_negotiated_prices(self):
        data = self.cleaned_data.get('negotiated_prices') or "{}"
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {}
        return parsed


class NewCustomerForm(forms.ModelForm):
    class Meta:
        model = CustomUser  # Since you're creating a CustomUser here for customers
        fields = ['first_name', 'last_name', 'phone_number']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ConfirmBranchForm(forms.Form):
    branches = forms.ModelChoiceField(
        queryset=models.Branch.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Select Branch"
    )


class WorkerProfileForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['gh_card_number', 'gh_card_photo', 'pending_phone_number']
        labels = {
            'pending_phone_number': 'Phone Number',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        worker = kwargs.get('instance')
        if worker:
            # Handle GH Card approval
            if worker.is_gh_card_approved:
                self.fields['gh_card_number'].disabled = True
                self.fields['gh_card_photo'].disabled = True

            # Handle phone number approval
            if worker.is_phone_number_approved:
                self.fields['pending_phone_number'].initial = worker.user.phone_number
            else:
                self.fields['pending_phone_number'].initial = worker.pending_phone_number
                self.fields['pending_phone_number'].help_text = 'Your new phone number is pending approval.'

            if worker.is_phone_number_approved:
                self.fields['pending_phone_number'].disabled = False
            else:
                self.fields['pending_phone_number'].disabled = True  #


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'location', 'phone_number', 'email']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter branch name',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter branch location',
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter branch contact phone number',
            }),
            'email': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter branch contact email',
            }),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['description', 'amount', 'branch']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'step': 0.01, 'class': 'form-control'}),
            'branch': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(ExpenseForm, self).__init__(*args, **kwargs)
        if user:
            if not user.is_staff and not user.is_superuser:
                try:
                    worker = user.worker_profile
                    self.fields['branch'].queryset = Branch.objects.filter(pk=worker.branch.pk)
                    self.fields['branch'].initial = worker.branch
                except Worker.DoesNotExist:
                    self.fields['branch'].queryset = Branch.objects.none()
            else:
                self.fields['branch'].queryset = Branch.objects.all()
        else:
            self.fields['branch'].queryset = Branch.objects.none()


class EnrollWorkerForm(forms.Form):
    # —————— User Info ——————
    first_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    phone_number = forms.CharField(max_length=15, widget=forms.TextInput(attrs={'class': 'form-control'}))

    # —————— Personal & ID ——————
    date_of_birth = forms.DateField(required=False,
                                    widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    place_of_birth = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    nationality = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    home_address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))
    landmark = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    ecowas_id_card_no = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    ecowas_id_card_photo = forms.ImageField(required=False)
    passport_photo = forms.ImageField(required=False)

    # —————— Education ——————
    school_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    school_location = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    year_completed = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))

    # —————— Employment ——————
    branch = forms.ModelChoiceField(queryset=Branch.objects.all(), widget=forms.Select(attrs={'class': 'form-select'}))
    employer_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    contact_number = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    location = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    position = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_date_of_work = forms.DateField(required=False,
                                        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    home_office_address = forms.CharField(required=False,
                                          widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))
    reason_for_leaving = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    may_we_contact = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    # —————— Reference ——————
    ref_full_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    ref_mobile_number = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    ref_address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))

    # —————— Guarantor ——————
    gua_full_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    gua_mobile_number = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    gua_address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))

    # —————— Other worker fields ——————
    position_job = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}),
                                   label="Job Title")
    salary = forms.FloatField(required=False, min_value=0, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    gh_card_number = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    year_of_admission = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    is_branch_admin = forms.BooleanField(required=False,
                                         widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
                                         label="Branch Admin?")


REPORT_TYPE_CHOICES = [
    ('branch', 'Branch Report'),
    ('worker', 'Worker Report'),
    ('customer', 'Customer Report'),
    ('services', 'Services Report'),
    ('products', 'Products Report'),
    ('financial', 'Financial Report'),
]

VIEW_TYPE_CHOICES = [
    ('date_range', 'Date Range'),
    ('month_year', 'Month & Year'),
]


class ReportForm(forms.Form):
    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        required=True,
        label="Report Type"
    )
    view_type = forms.ChoiceField(
        choices=VIEW_TYPE_CHOICES,
        required=True,
        label="View Type"
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Start Date"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="End Date"
    )

    month = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        label="Month"
    )
    year = forms.IntegerField(
        required=False,
        min_value=2000,
        max_value=2100,
        label="Year"
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        required=False,
        label="Branch"
    )
    worker = forms.ModelChoiceField(
        queryset=Worker.objects.all(),
        required=False,
        label="Worker"
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        label="Customer"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply Bootstrap form-control class to each field
        for field_name, field in self.fields.items():
            existing_classes = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing_classes} form-control'.strip()


class CreateCustomerForm(forms.Form):
    first_name = forms.CharField(
        max_length=100,
        label="First Name",
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': False})  # Bootstrap input
    )
    last_name = forms.CharField(
        max_length=100,
        label="Last Name",
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': False})  # Bootstrap input
    )
    phone_number = forms.CharField(
        max_length=15,
        label="Phone Number",
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': False})  # Bootstrap input
    )
    email = forms.EmailField(
        required=False,
        label="Email (Optional)",
        widget=forms.EmailInput(attrs={'class': 'form-control', 'required': False})  # Bootstrap input
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        label="Select Branch",
        widget=forms.Select(attrs={'class': 'form-select'})  # Bootstrap select
    )
    customer_group = forms.ChoiceField(
        choices=(("Credit Customer", "Credit Customer"), ("Cash Customer", "Cash Customer")),
        widget=forms.Select(attrs={'class': 'form-select'}))
    vehicle_group = forms.ModelChoiceField(
        queryset=VehicleGroup.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
        label="Vehicle Group"
    )
    car_make = forms.CharField(max_length=100, required=True, label="Car Make",
                               widget=forms.TextInput(attrs={'class': 'form-control'}))
    car_plate = forms.CharField(max_length=100, required=True, label="Car Plate",
                                widget=forms.TextInput(attrs={'class': 'form-control'}))
    car_color = forms.CharField(max_length=100, required=True, label="Car Color",
                                widget=forms.TextInput(attrs={'class': 'form-control'}))


class CreateVehicleForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        label="Select Customer",
        widget=forms.Select(attrs={'class': 'form-select'}),  # Bootstrap select
        required=False  # This makes the field optional
    )
    vehicle_group = forms.ModelChoiceField(
        queryset=VehicleGroup.objects.all(),
        label="Select Vehicle Group",
        widget=forms.Select(attrs={'class': 'form-select'})  # Bootstrap select
    )
    car_make = forms.CharField(
        max_length=100,
        label="Car Make",
        widget=forms.TextInput(attrs={'class': 'form-control'})  # Bootstrap input
    )
    car_plate = forms.CharField(
        max_length=100,
        label="Car Plate",
        widget=forms.TextInput(attrs={'class': 'form-control'})  # Bootstrap input
    )
    car_color = forms.CharField(
        max_length=50,
        required=False,
        label="Car Color (Optional)",
        widget=forms.TextInput(attrs={'class': 'form-control'})  # Bootstrap input
    )


class EditCustomerVehicleForm(forms.ModelForm):
    class Meta:
        model = CustomerVehicle
        fields = ['customer', 'vehicle_group', 'car_plate', 'car_make', 'car_color']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add the 'form-control' class to each widget for Bootstrap styling
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CustomerEditForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(max_length=15, required=False)

    class Meta:
        model = Customer
        fields = ['branch', 'loyalty_points', 'customer_group', 'first_name', 'last_name', 'email', 'phone_number']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email
            self.fields['phone_number'].initial = self.instance.user.phone_number

        # Add Bootstrap styling to all form fields
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

    def save(self, commit=True):
        customer = super().save(commit=False)
        user = customer.user
        user.first_name = self.cleaned_data.get('first_name')
        user.last_name = self.cleaned_data.get('last_name')
        user.email = self.cleaned_data.get('email')
        user.phone_number = self.cleaned_data.get('phone_number')
        if commit:
            user.save()
            customer.save()
        return customer


class LogServiceScannedForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=CustomerVehicle.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'vehicle-select-scanned'}),
        empty_label="Select Vehicle",
        required=False
    )
    service = forms.ModelMultipleChoiceField(
        queryset=Service.objects.none(),
        widget=forms.SelectMultiple(attrs={
            'class': 'form-control',
            'placeholder': 'Select services',
            'id': 'service-select-scanned',
        }),
    )
    workers = forms.ModelMultipleChoiceField(
        queryset=None,
        label="Select Workers",
        widget=forms.SelectMultiple(attrs={
            'class': 'form-control',
            'placeholder': 'Select Workers',
        }),
    )
    comments = forms.CharField(widget=forms.Textarea, required=False)
    negotiated_prices = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, branch, customer, *args, **kwargs):
        """
        branch: worker.branch
        customer: The Customer object (already known from scanned link).
        """
        super().__init__(*args, **kwargs)

        # Workers are from the same branch as the scanning worker
        self.fields['workers'].queryset = Worker.objects.filter(branch=branch)

        # Vehicles only belong to this specific customer
        self.fields['vehicle'].queryset = CustomerVehicle.objects.filter(customer=customer)

        # If there's a "vehicle" in data or initial, limit the services
        if 'vehicle' in self.data:
            try:
                vehicle_id = int(self.data.get('vehicle'))
                vehicle_obj = CustomerVehicle.objects.get(id=vehicle_id)
                vehicle_group = vehicle_obj.vehicle_group
                self.fields['service'].queryset = Service.objects.filter(vehicle_group=vehicle_group, active=True)
            except (ValueError, TypeError, CustomerVehicle.DoesNotExist):
                pass
        elif self.initial.get('vehicle'):
            try:
                vehicle_obj = CustomerVehicle.objects.get(id=self.initial['vehicle'])
                vehicle_group = vehicle_obj.vehicle_group
                self.fields['service'].queryset = Service.objects.filter(vehicle_group=vehicle_group, active=True)
            except (ValueError, TypeError, CustomerVehicle.DoesNotExist):
                pass
        else:
            self.fields['service'].queryset = Service.objects.none()

    def clean_service(self):
        services = self.cleaned_data.get('service')
        if not services:
            raise forms.ValidationError("Please select at least one service.")
        return services

    def clean_negotiated_prices(self):
        data = self.cleaned_data.get('negotiated_prices') or "{}"
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {}
        return parsed


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'phone_number', 'email', 'address']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = False
        self.fields['address'].required = False


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class CustomerBookingForm(forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=CustomerVehicle.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Vehicle"
    )
    services = forms.ModelMultipleChoiceField(
        queryset=Service.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
        label="Services"
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Branch"
    )
    scheduled_at = forms.DateTimeField(
        widget=DateTimeInput(attrs={"class": "form-control", "min": timezone.now().strftime("%Y-%m-%dT%H:%M")}),
        label="Scheduled date & time",
        help_text="When you plan to bring the vehicle in."
    )
    driver_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="Driver name"
    )
    driver_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 024xxxxxxx"}),
        label="Driver phone"
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        label="Notes / special requests"
    )

    class Meta:
        model = CustomerBooking
        fields = ["vehicle", "services", "branch", "scheduled_at", "driver_name", "driver_phone", "notes"]

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)
        vehicle_id = kwargs.pop("vehicle_id", None)
        super().__init__(*args, **kwargs)

        # Limit vehicles to the current customer's vehicles
        if customer:
            self.fields["vehicle"].queryset = CustomerVehicle.objects.filter(customer=customer).select_related("vehicle_group")

        # If a vehicle is preselected (GET or POST), filter services by that vehicle's group
        vg = None
        if vehicle_id:
            try:
                vg = CustomerVehicle.objects.select_related("vehicle_group").get(id=vehicle_id).vehicle_group
            except CustomerVehicle.DoesNotExist:
                vg = None
        elif self.instance and self.instance.vehicle_id:
            vg = self.instance.vehicle.vehicle_group

        if vg:
            self.fields["services"].queryset = Service.objects.filter(active=True, vehicle_group=vg).order_by("service_type")
        else:
            # If no vehicle picked yet, show nothing until chosen
            self.fields["services"].queryset = Service.objects.none()

    def clean(self):
        cleaned = super().clean()
        vehicle = cleaned.get("vehicle")
        services = cleaned.get("services")

        # Ensure the selected services belong to the chosen vehicle's group
        if vehicle and services:
            valid_services = Service.objects.filter(active=True, vehicle_group=vehicle.vehicle_group)
            invalid = [s for s in services if s not in valid_services]
            if invalid:
                self.add_error(
                    "services",
                    "One or more selected services are not available for this vehicle type."
                )
        return cleaned


class CustomerBookingEditForm(forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=None,  # set in __init__
        widget=forms.Select(attrs={"class": "form-control", "id": "id_vehicle"}),
        empty_label="Select Vehicle",
    )
    services = forms.ModelMultipleChoiceField(
        queryset=None,  # set in __init__
        widget=forms.SelectMultiple(attrs={"class": "form-control", "id": "id_services"}),
        required=True,
    )

    class Meta:
        model = CustomerBooking
        fields = ["scheduled_at", "driver_name", "driver_phone", "notes", "vehicle", "services"]
        widgets = {
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "driver_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Driver full name"}),
            "driver_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Driver phone"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Additional info"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Expects `customer` kwarg to limit vehicles to the current user.
        Dynamically filters services by selected vehicle's vehicle_group.
        """
        self.customer = kwargs.pop("customer", None)
        super().__init__(*args, **kwargs)

        # Vehicles: only this customer's
        from autodash_App import models as m  # adjust if your models import path differs
        if self.customer:
            self.fields["vehicle"].queryset = m.CustomerVehicle.objects.filter(customer=self.customer).select_related("vehicle_group")
        else:
            self.fields["vehicle"].queryset = m.CustomerVehicle.objects.none()

        # Decide which vehicle to use for filtering services
        vehicle_obj = None
        if self.is_bound:
            try:
                vid = int(self.data.get("vehicle") or 0)
                vehicle_obj = m.CustomerVehicle.objects.filter(id=vid, customer=self.customer).select_related("vehicle_group").first()
            except (TypeError, ValueError):
                vehicle_obj = None
        elif self.instance and self.instance.pk:
            vehicle_obj = self.instance.vehicle

        # Services: by vehicle group (if we have one); else empty
        if vehicle_obj and vehicle_obj.vehicle_group_id:
            self.fields["services"].queryset = m.Service.objects.filter(
                vehicle_group=vehicle_obj.vehicle_group, active=True
            ).only("id", "service_type")
        else:
            self.fields["services"].queryset = m.Service.objects.none()

        # Preselect current services on initial load
        if not self.is_bound and self.instance and self.instance.pk:
            self.initial.setdefault("services", self.instance.services.values_list("id", flat=True))

    def clean_scheduled_at(self):
        dt = self.cleaned_data.get("scheduled_at")
        if dt and dt < timezone.now():
            raise forms.ValidationError("Scheduled time cannot be in the past.")
        return dt

    def clean_services(self):
        svcs = self.cleaned_data.get("services")
        vehicle = self.cleaned_data.get("vehicle")
        if not svcs:
            raise forms.ValidationError("Please select at least one service.")
        if not vehicle or not getattr(vehicle, "vehicle_group_id", None):
            raise forms.ValidationError("Select a vehicle before choosing services.")
        bad = [s for s in svcs if s.vehicle_group_id != vehicle.vehicle_group_id]
        if bad:
            raise forms.ValidationError("One or more selected services do not match the selected vehicle type.")
        return svcs



