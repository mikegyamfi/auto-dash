"""
Two live 500s.

  * `export_service_history_pdf` called xhtml2pdf's `pisa`, whose import is
    commented out at the top of views.py — so every request raised NameError.
    It is now built with reportlab, like the arrears export.

  * `dormant_vehicles` reversed `customer_detail` with the customer's id, but
    `CustomerVehicle.customer` is nullable, so one orphaned vehicle anywhere in
    the results took the whole page down with NoReverseMatch.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autodash_App.models import (
    Branch, Customer, CustomUser, CustomerVehicle, ServiceRenderedOrder,
    VehicleGroup, Worker, WorkerCategory,
)


class ServiceHistoryPdfExportTest(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.group = VehicleGroup.objects.create(group_name="Saloon")
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="customer", approved=True,
            first_name="Ama", last_name="Mensah", phone_number="0247777777",
        )
        self.customer = Customer.objects.create(user=user, branch=self.branch)
        self.vehicle = CustomerVehicle.objects.create(
            customer=self.customer, vehicle_group=self.group,
            car_plate="GR-213-21", car_make="Toyota", car_color="Grey",
        )
        ServiceRenderedOrder.objects.create(
            user=self.staff, customer=self.customer, vehicle=self.vehicle,
            branch=self.branch, total_amount=100.0, final_amount=100.0,
            status="completed", cash_paid=100.0,
        )
        self.client.force_login(self.staff)

    def _pdf(self, **params):
        return self.client.get(reverse("export_service_history_pdf"), params)

    def test_it_no_longer_raises(self):
        """The regression: this used to be a 500 on every request."""
        self.assertEqual(self._pdf().status_code, 200)

    def test_it_returns_a_real_pdf(self):
        response = self._pdf()
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_it_renders_the_rows(self):
        wide = self._pdf(start_date="2020-01-01", end_date="2030-12-31")
        empty = self._pdf(start_date="2020-01-01", end_date="2020-01-02")
        self.assertGreater(len(wide.content), len(empty.content))

    def test_an_empty_range_still_produces_a_pdf(self):
        response = self._pdf(start_date="2020-01-01", end_date="2020-01-02")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_a_walk_in_order_does_not_break_it(self):
        """No customer record; display_customer_name covers both."""
        ServiceRenderedOrder.objects.create(
            user=self.staff, branch=self.branch, total_amount=50.0,
            final_amount=50.0, status="completed", cash_paid=50.0,
            is_walkin=True, walkin_name="Kofi", walkin_vehicle_plate="GT-1-24",
            walkin_vehicle_make="Kia",
        )
        response = self._pdf(start_date="2020-01-01", end_date="2030-12-31")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_the_excel_export_still_works(self):
        response = self.client.get(reverse("export_service_history_excel"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])


class DormantVehiclesTest(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            name="Ridge", location="Accra", phone_number="0240000000"
        )
        self.group = VehicleGroup.objects.create(group_name="Saloon")
        self.staff = CustomUser.objects.create_user(
            username="0248888888", password="x", role="worker",
            is_staff=True, is_superuser=True, approved=True,
        )
        user = CustomUser.objects.create_user(
            username="0247777777", password="x", role="customer", approved=True,
            first_name="Ama", last_name="Mensah", phone_number="0247777777",
        )
        self.customer = Customer.objects.create(user=user, branch=self.branch)
        self.owned = CustomerVehicle.objects.create(
            customer=self.customer, vehicle_group=self.group,
            car_plate="GR-213-21", car_make="Toyota", car_color="Grey",
        )
        self.client.force_login(self.staff)

    def test_it_renders(self):
        self.assertEqual(
            self.client.get(reverse("dormant_vehicles")).status_code, 200
        )

    def test_an_orphaned_vehicle_does_not_take_the_page_down(self):
        """The regression: NoReverseMatch on customer_id=''."""
        CustomerVehicle.objects.create(
            customer=None, vehicle_group=self.group,
            car_plate="GT-999-99", car_make="Kia", car_color="Blue",
        )
        response = self.client.get(reverse("dormant_vehicles"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GT-999-99")
        self.assertContains(response, "No owner on record")

    def test_an_owned_vehicle_still_links_to_its_customer(self):
        response = self.client.get(reverse("dormant_vehicles"))
        self.assertContains(
            response, reverse("customer_detail", args=[self.customer.id])
        )

    def test_deleting_an_orphaned_vehicle_owner_does_not_crash(self):
        orphan = CustomerVehicle.objects.create(
            customer=None, vehicle_group=self.group,
            car_plate="GT-999-99", car_make="Kia", car_color="Blue",
        )
        response = self.client.post(reverse("dormant_vehicles"), {
            "action": "delete_customer", "vehicle_id": orphan.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CustomerVehicle.objects.filter(pk=orphan.pk).exists())

    def test_deleting_a_vehicle_still_works(self):
        self.client.post(reverse("dormant_vehicles"), {
            "action": "delete_vehicle", "vehicle_id": self.owned.id,
        })
        self.assertFalse(CustomerVehicle.objects.filter(pk=self.owned.pk).exists())

    def test_a_branch_admin_sees_their_own_branch(self):
        category = WorkerCategory.objects.create(name="Lead", service_provider=False)
        user = CustomUser.objects.create_user(
            username="0246666666", password="x", role="worker", approved=True
        )
        Worker.objects.create(
            user=user, branch=self.branch, worker_category=category,
            is_branch_admin=True,
        )
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse("dormant_vehicles")).status_code, 200
        )

    def test_staff_without_a_worker_profile_do_not_crash(self):
        """`user.worker_profile` does not exist for a bare staff account."""
        bare = CustomUser.objects.create_user(
            username="0245555555", password="x", role="worker",
            is_staff=True, approved=True,
        )
        self.client.force_login(bare)
        self.assertEqual(
            self.client.get(reverse("dormant_vehicles")).status_code, 200
        )
