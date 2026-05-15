from django.contrib import admin

from .models import (
    Bill,
    BillItem,
    BusinessSubscription,
    BusinessProfile,
    Category,
    Customer,
    LoginOTP,
    Product,
    SubscriptionPlan,
    SubscriptionPaymentOrder,
    UserProfile,
)


class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "business_type", "phone", "email", "gstin")
    search_fields = ("name", "phone", "email", "gstin")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "billing_cycle", "max_users", "max_products", "is_active")
    list_filter = ("billing_cycle", "is_active")
    search_fields = ("name", "code", "description")


@admin.register(BusinessSubscription)
class BusinessSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("business", "plan", "status", "starts_at", "ends_at", "days_remaining", "seats")
    list_filter = ("status", "plan", "ends_at")
    search_fields = ("business__name", "business__phone", "business__email", "plan__name")


@admin.register(SubscriptionPaymentOrder)
class SubscriptionPaymentOrderAdmin(admin.ModelAdmin):
    list_display = ("razorpay_order_id", "business", "plan", "amount", "currency", "status", "created_at")
    list_filter = ("status", "currency", "plan")
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "receipt", "business__name", "business__phone")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "business_profile", "created_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(LoginOTP)
class LoginOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "user", "purpose", "expires_at", "verified_at", "attempts")
    list_filter = ("purpose", "verified_at", "expires_at")
    search_fields = ("phone", "user__username", "user__email")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "parent", "gst_rate", "display_order", "is_active")
    list_filter = ("is_active", "gst_rate")
    search_fields = ("name", "code", "description")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "selling_price", "stock_quantity", "unit_type", "is_active")
    list_filter = ("category", "unit_type", "is_active")
    search_fields = ("name", "barcode", "description")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "city", "customer_type", "credit_limit")
    list_filter = ("customer_type", "city")
    search_fields = ("full_name", "phone", "email", "gstin")


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ("invoice_id", "customer", "payment_mode", "grand_total", "is_paid", "created_at")
    list_filter = ("payment_mode", "is_paid", "created_at")
    search_fields = ("invoice_id", "customer__full_name", "customer__phone")
    inlines = (BillItemInline,)
