from django.urls import path

from autodash_App import views
from autodash_App.auth import auth_views

urlpatterns = [
    path('', views.home, name='index'),
    path('log_service', views.log_service, name='log_service'),
    path('check-customer-status/<int:customer_id>/', views.check_customer_status, name='check_customer_status'),

    # URL path for creating a new customer via modal
    path('create-customer/', views.create_customer, name='create_customer'),

    # URL path for viewing service history
    path('service-history/', views.service_history, name='service_history'),
    path('confirm_service_rendered/<int:pk>', views.confirm_service, name='confirm_service_rendered'),
    path('discard_order/<int:pk>', views.discard_order, name='discard_order'),

    # ==================================================================================
    path('worker_sign_up', auth_views.worker_sign_up, name='worker_register'),
    path('worker_confirm_branch', auth_views.confirm_branch_of_work, name='worker_confirm_branch'),
    path('thank_you_for_feedback/<int:pk>', views.thank_you_feedback, name='thank_you_for_feedback'),

    path('feedback/<int:pk>', views.service_feedback_page, name='service_feedback'),
    path('service-order-details/<int:pk>/', views.service_order_details, name='service_order_details'),

    path('get_customer_vehicles/<int:customer_id>/', views.get_customer_vehicles, name='get_customer_vehicles'),
    path('create_vehicle/', views.create_vehicle, name='create_vehicle'),
    path('get_vehicle_services/<int:vehicle_id>/', views.get_vehicle_services, name='get_vehicle_services'),
    path('customers/', views.branch_customers, name='branch_customers'),
    path('customer/<int:customer_id>/', views.customer_detail, name='customer_detail'),
    path('customer/<int:customer_id>/add_vehicle/', views.add_vehicle_to_customer, name='add_vehicle_to_customer'),

    path('worker/profile/', views.worker_profile, name='worker_profile'),
    path('elevated/approve-workers/', views.approve_workers, name='approve_workers'),
    path('elevated/approve-worker/<int:worker_id>/<str:approval_type>/', views.approve_worker, name='approve_worker'),
    path('elevated/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('elevated/branches/', views.manage_branches, name='manage_branches'),
    # path('elevated/branches/add/', views.add_branch, name='add_branch'),  # Optional
    # path('elevated/branches/edit/<int:branch_id>/', views.edit_branch, name='edit_branch'),  # Optional
    path('elevated/workers/', views.manage_workers, name='manage_workers'),
    path('elevated/workers/<int:worker_id>/', views.worker_detail, name='worker_detail'),
    path('elevated/customers/', views.manage_customers, name='manage_customers'),
    path('elevated/customers/<int:customer_id>/', views.customer_detail_admin, name='customer_detail_admin'),
    path('elevated/vehicle-groups/', views.vehicle_groups, name='vehicle_groups'),
    path('elevated/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin_dashboard/get_branch_comparison_data/', views.get_branch_comparison_data,
         name='get_branch_comparison_data'),
path('admin_dashboard/get_service_performance_data/', views.get_service_performance_data, name='get_service_performance_data'),
    path('admin_dashboard/get_vehicles_data/', views.get_vehicles_data, name='get_vehicles_data'),
    path('elevated/branch-insights/<int:branch_id>/', views.branch_insights, name='branch_insights'),
    path('elevated/add_branch', views.add_branch, name='add_branch'),
    path('elevated/edit_branch/<int:branch_id>/', views.edit_branch, name='edit_branch'),
    path('elevated/delete_branch/<int:branch_id>/', views.delete_branch, name='delete_branch'),

    # ===================================================== Customer URLS ===============================================================
    path('customer/dashboard/', views.customer_dashboard, name='customer_dashboard'),
    path('customer-service-history/', views.customer_service_history, name='customer_service_history'),
    path('login', auth_views.login_page, name='login'),
    path('logout', auth_views.logout_page, name='logout'),
]
