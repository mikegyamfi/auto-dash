from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from autodash_App import models
from autodash_App.models import ServiceRendered, Customer, CustomUser, Service, Worker, Branch


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
        empty_label="Select Customer"
    )

    vehicle = forms.ModelChoiceField(
        queryset=models.CustomerVehicle.objects.none(),
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
        widget=forms.SelectMultiple(attrs={
            'class': 'form-control',
            'placeholder': 'Select Workers',
        }),
    )

    def __init__(self, branch, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['workers'].queryset = Worker.objects.filter(branch=branch)

        # Set vehicle queryset based on customer
        if 'customer' in self.data:
            try:
                customer_id = int(self.data.get('customer'))
                self.fields['vehicle'].queryset = models.CustomerVehicle.objects.filter(customer_id=customer_id)
            except (ValueError, TypeError):
                pass  # Invalid input

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


