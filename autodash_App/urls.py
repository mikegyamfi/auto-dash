from django.urls import path
from django.conf.urls.static import static
from django.conf import settings
from autodash_App import views
from autodash_App.auth import auth_views
from autodash_App.views import standalone_product_receipt, worker_commissions, enroll_worker, generate_report, \
    create_customer_page, create_vehicle_page

urlpatterns = [
                  path('', views.home, name='index'),
                  path('log_service', views.log_service, name='log_service'),
                  path('log_scanned_service/<int:customer_id>', views.log_service_scanned, name='log_service_scanned'),
                  path('check-customer-status/<int:customer_id>/', views.check_customer_status,
                       name='check_customer_status'),
                  path('elevated/select_branch/', views.home, name='select_branch'),  # Admin branch selection
                  path('elevated/dashboard/', views.home, name='admin_dashboard'),

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

                  path('get_customer_vehicles/<int:customer_id>/', views.get_customer_vehicles,
                       name='get_customer_vehicles'),
                  path('create_vehicle/', views.create_vehicle, name='create_vehicle'),
                  path('get_vehicle_services/<int:vehicle_id>/', views.get_vehicle_services,
                       name='get_vehicle_services'),
                  path('customers/', views.branch_customers, name='branch_customers'),
                  path('customer/<int:customer_id>/', views.customer_detail, name='customer_detail'),
                  path('customer/<int:customer_id>/add_vehicle/', views.add_vehicle_to_customer,
                       name='add_vehicle_to_customer'),

                  path('worker/profile/', views.worker_profile, name='worker_profile'),
                  path('elevated/approve-workers/', views.approve_workers, name='approve_workers'),
                  path('elevated/approve-worker/<int:worker_id>/<str:approval_type>/', views.approve_worker,
                       name='approve_worker'),
                  path('elevated/dashboard/', views.admin_dashboard, name='admin_dashboard'),
                  path('elevated/branches/', views.manage_branches, name='manage_branches'),
                  # path('elevated/branches/add/', views.add_branch, name='add_branch'),  # Optional
                  # path('elevated/branches/edit/<int:branch_id>/', views.edit_branch, name='edit_branch'),  # Optional
                  path('elevated/workers/', views.manage_workers, name='manage_workers'),
                  path('elevated/workers/<int:worker_id>/', views.worker_detail, name='worker_detail'),
                  path('elevated/customers/', views.manage_customers, name='manage_customers'),
                  path('elevated/customers/<int:customer_id>/', views.customer_detail_admin,
                       name='customer_detail_admin'),
                  path('elevated/enrol_customer_in_subscription/<int:customer_id>', views.enroll_subscription,
                       name='enrol_customer_in_subscription'),
                  path('elevated/renew_customer_subscription/<int:customer_id>', views.renew_subscription,
                       name='renew_customer_subscription'),
                  path('elevated/vehicle-groups/', views.vehicle_groups, name='vehicle_groups'),
                  path('elevated/dashboard_analytics/', views.analytics_dashboard, name='admin_analytics'),
                  path('elevated/sales-targets/', views.sales_targets_manage, name='sales_targets_manage'),
                  path('elevated/sales-target_report/', views.sales_targets_report, name='sales_targets_report'),
                  path('admin_dashboard/get_branch_comparison_data/', views.get_branch_comparison_data,
                       name='get_branch_comparison_data'),
                  path('admin_dashboard/get_service_performance_data/', views.get_service_performance_data,
                       name='get_service_performance_data'),
                  path('admin_dashboard/get_vehicles_data/', views.get_vehicles_data, name='get_vehicles_data'),
                  path('elevated/enroll-worker/', enroll_worker, name='enroll_worker'),
                  path('elevated/branch-insights/<int:branch_id>/', views.branch_insights, name='branch_insights'),
                  path('elevated/add_branch', views.add_branch, name='add_branch'),
                  path('elevated/edit_branch/<int:branch_id>/', views.edit_branch, name='edit_branch'),
                  path('elevated/delete_branch/<int:branch_id>/', views.delete_branch, name='delete_branch'),

                  # ===================================================== Customer URLS ===============================================================
                  path('customer/dashboard/', views.customer_dashboard, name='customer_dashboard'),
                  path('customer/my_profile', views.customer_profile, name='customer_profile'),
                  path('customer-service-history/', views.customer_service_history, name='customer_service_history'),
                  path('login', auth_views.login_page, name='login'),
                  path('logout', auth_views.logout_page, name='logout'),

                  path('expenses/', views.expense_list, name='expense_list'),
                  path('expenses/add/', views.add_expense, name='add_expense'),
                  path('sell_product', views.standalone_product_sale, name='sell_product'),
                  path('standalone_product_receipt/<uuid:batch_id>/', standalone_product_receipt,
                       name='standalone_product_receipt'),
                  path('elevated/generate-report/', generate_report, name='generate_report'),
                  path('expenses/edit/<int:pk>/', views.edit_expense, name='edit_expense'),
                  path('expenses/delete/<int:pk>/', views.delete_expense, name='delete_expense'),

                  path('elevated/commissions/', views.commissions_by_date, name='commissions_by_date'),
                  path('elevated/commission_breakdown', views.commission_breakdown, name='commission_breakdown'),
                  path('worker-commissions/', worker_commissions, name='worker_commissions'),
                  path('elevated/expenses/', views.expenses_by_date, name='expenses_by_date'),
                  path('elevated/financial-overview/', views.financial_overview, name='financial_overview'),
                  path('elevated/product-sales-report/', views.product_sales_report, name='product_sales_report'),
                  path('elevated/arrears/', views.arrears_list, name='arrears_list'),
                  path('elevated/arrears/<int:arrears_id>/mark-paid/', views.mark_arrears_as_paid,
                       name='mark_arrears_as_paid'),
                  path('arrears/<int:arrears_id>/details/', views.arrears_details, name='arrears_details'),
                  path('arrears/<int:arrears_id>/send-reminder/', views.send_arrears_reminder,
                       name='send_arrears_reminder'),
                  path('elevated/create-customer/', create_customer_page, name='create_customer_page'),
                  path('elevated/create-vehicle/', create_vehicle_page, name='create_vehicle_page'),
                  path('approve-worker/<int:worker_id>/', views.approve_worker, name='approve_worker'),

                  # 1) Add a vehicle to customer
                  path('customer/<int:customer_id>/add_vehicle/',
                       views.customer_page_add_vehicle_to_customer,
                       name='add_vehicle_to_customer'),

                  # 2) Remove a vehicle from customer
                  path('customer/<int:customer_id>/remove_vehicle/',
                       views.customer_page_remove_vehicle_from_customer,
                       name='remove_vehicle_from_customer'),

                  # 3) Add a subscription to customer
                  path('customer/<int:customer_id>/add_subscription/',
                       views.customer_page_add_subscription_to_customer,
                       name='add_subscription_to_customer'),

                  # 4) Service order details page
                  path('service/<int:pk>/details/',
                       views.service_order_details,
                       name='service_order_details'),

                  path('service/<int:pk>/receipt/', views.service_receipt, name='service_receipt'),
                  path('vehicles/', views.vehicle_list, name='vehicle_list'),
                  path('vehicles/edit/<int:pk>/', views.edit_vehicle, name='edit_vehicle'),
                  path('customer/edit/<int:customer_id>/', views.edit_customer, name='edit_customer'),
                  path('generate_customer_subscription_card/<int:subscription_id>', views.generate_subscription_card,
                       name='generate_subscription_card'),
                  path('budget_analysis', views.daily_budget_insights, name='daily_budget_insights'),
                  path("budgets/weekly/", views.set_weekly_budgets, name="set_weekly_budgets"),
                  path('elevated/dormant_vehicles', views.dormant_vehicles, name='dormant_vehicles'),
                  path(
                      'service-history/export/excel/',
                      views.export_service_history_excel,
                      name='export_service_history_excel'
                  ),
                  path(
                      'service-history/export/pdf/',
                      views.export_service_history_pdf,
                      name='export_service_history_pdf'
                  ),

                  path(
                      'elevated/customers/<int:customer_id>/generate_history_link/',
                      views.generate_history_link,
                      name='generate_history_link'
                  ),
                  path(
                      'history/access/<str:customer_phone>/',
                      views.customer_history_access,
                      name='customer_history_access'
                  ),
                  path('customer/book_service', views.create_customer_booking, name='book_service'),
                  path('customer/booking_history', views.customer_booking_history, name='booking_history'),
                  path("customer/booking/services-for-vehicle/", views.booking_services_for_vehicle,
                       name="booking_services_for_vehicle"),
                  path("booking/<int:pk>/convert/", views.convert_booking, name="booking_convert"),
                  path("booking/<int:pk>/", views.customer_booking_detail, name="customer_booking_detail"),
                  path("booking/<int:pk>/edit/", views.customer_booking_edit, name="customer_booking_edit"),
                  path("booking/<int:pk>/mark-arrived/", views.booking_mark_arrived, name="booking_mark_arrived"),
                  path(
                      "api/booking/services-for-vehicle/",
                      views.booking_services_for_vehicle,
                      name="booking_services_for_vehicle",
                  ),
                  path(
                      "api/booking/service-meta/",
                      views.booking_service_meta,
                      name="booking_service_meta",
                  ),
                  path("customer/vehicle/add/", views.customer_vehicle_create, name="customer_vehicle_create"),
                  path("customer/vehicles/", views.customer_vehicles, name="customer_vehicles"),

                  path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
                  path("notifications/mark-all-read/", views.notification_mark_all_read,
                       name="notifications_mark_all_read"),
                  path("notifications/", views.notifications_list, name="notifications_list"),

                  path("other-services/new/", views.other_service_create, name="other_service_create"),
                  path("other-services/", views.other_service_history, name="other_service_history"),
                  path("other-services/<int:pk>/status/<str:new_status>/", views.other_service_update_status,
                       name="other_service_update_status"),

                  path("maintenance/", views.maintenance_list, name="maintenance_list"),
                  path("maintenance/new/", views.maintenance_create, name="maintenance_create"),
                  path("maintenance/<int:pk>/", views.maintenance_detail, name="maintenance_detail"),
                  path("maintenance/<int:pk>/edit/", views.maintenance_edit, name="maintenance_edit"),
                  path("maintenance/<int:pk>/add-expense/", views.maintenance_add_expense,
                       name="maintenance_add_expense"),
                  path("maintenance/<int:pk>/resolve/", views.maintenance_mark_resolved,
                       name="maintenance_mark_resolved"),
                  path('reports/workers/', views.worker_report_view, name='worker_report'),
                  path('reports/branch-activity/', views.branch_activity_report_view,
                       name='branch_activity_report'),
                  path('reports/customers/', views.customer_report_view, name='customer_report'),
                  path('reports/products/', views.product_sales_report_view, name='product_report'),
              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
