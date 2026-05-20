from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    BillViewSet,
    BusinessProfileViewSet,
    CategoryViewSet,
    CustomerViewSet,
    FirebaseLoginView,
    OTPRequestView,
    OTPVerifyView,
    ProductViewSet,
    RegisterView,
    account_delete,
    account_delete_request,
    app_update_check,
    app_subscription,
    bill_pdf,
    business_subscription_save,
    create_subscription_razorpay_order,
    dashboard_summary,
    health_check,
    legal_document,
    product_unit_types,
    reports_download,
    reports_summary,
    support_contact,
    subscription_admin_panel,
    subscription_admin_logout,
    subscription_owner_login,
    subscription_plans,
    subscription_plan_create,
    verify_subscription_razorpay_payment,
)

router = DefaultRouter()
router.register("business-profiles", BusinessProfileViewSet, basename="business-profile")
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
router.register("customers", CustomerViewSet, basename="customer")
router.register("bills", BillViewSet, basename="bill")

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/request-otp/", OTPRequestView.as_view(), name="auth-request-otp"),
    path("auth/verify-otp/", OTPVerifyView.as_view(), name="auth-verify-otp"),
    path("auth/firebase-login/", FirebaseLoginView.as_view(), name="auth-firebase-login"),
    path("auth/login/", TokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("app/update/", app_update_check, name="app-update-check"),
    path("legal/<str:document_type>/", legal_document, name="legal-document"),
    path("support/contact/", support_contact, name="support-contact"),
    path("account/delete-request/", account_delete_request, name="account-delete-request"),
    path("account/", account_delete, name="account-delete"),
    path("dashboard/summary/", dashboard_summary, name="dashboard-summary"),
    path("subscription/plans/", subscription_plans, name="subscription-plans"),
    path("subscription/current/", app_subscription, name="app-subscription"),
    path(
        "subscription/razorpay/create-order/",
        create_subscription_razorpay_order,
        name="subscription-razorpay-create-order",
    ),
    path(
        "subscription/razorpay/verify/",
        verify_subscription_razorpay_payment,
        name="subscription-razorpay-verify",
    ),
    path("reports/summary/", reports_summary, name="reports-summary"),
    path("reports/download/", reports_download, name="reports-download"),
    path("bills/<int:bill_id>/pdf/", bill_pdf, name="bill-pdf"),
    path("products/unit-types/", product_unit_types, name="product-unit-types"),
    path("subscription-admin/login/", subscription_owner_login, name="subscription-owner-login"),
    path("subscription-admin/", subscription_admin_panel, name="subscription-admin-panel"),
    path("subscription-admin/logout/", subscription_admin_logout, name="subscription-admin-logout"),
    path("subscription-admin/plans/", subscription_plan_create, name="subscription-plan-create"),
    path("subscription-admin/subscriptions/", business_subscription_save, name="business-subscription-save"),
]

urlpatterns += router.urls
