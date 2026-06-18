from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from decimal import Decimal
from rest_framework import serializers

from .models import (
    Bill,
    BillItem,
    BusinessProfile,
    BusinessSubscription,
    Category,
    CreditCustomer,
    CreditPayment,
    Customer,
    Product,
    SubscriptionPlan,
    UserProfile,
)


def build_absolute_media_url(value, request):
    if not value:
        return ""

    url = str(value)
    if url.startswith(("http://", "https://", "file://")):
        return url

    media_url = settings.MEDIA_URL if settings.MEDIA_URL.startswith("/") else f"/{settings.MEDIA_URL}"
    if url.startswith("/"):
        path = url
    elif url.startswith(media_url.lstrip("/")):
        path = f"/{url}"
    else:
        path = f"{media_url.rstrip('/')}/{url}"

    if request:
        return request.build_absolute_uri(path)

    return path


def build_full_media_url(obj, request):
    if not obj.image:
        return ""

    return build_absolute_media_url(obj.image.url, request)


def normalize_local_phone_number(value):
    digits = "".join(character for character in str(value or "") if character.isdigit())

    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]

    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]

    return digits


def first_present(data, keys):
    for key in keys:
        if key in data and data.get(key) not in (None, ""):
            return data.get(key)
    return ""


def normalize_lookup_value(value):
    return "".join(character for character in str(value or "").lower() if character.isalnum())


BUSINESS_TYPE_ALIASES = {
    "food": "Food shop",
    "foodshop": "Food shop",
    "restaurant": "Food shop",
    "hotel": "Food shop",
    "medical": "Medical shop",
    "medicalshop": "Medical shop",
    "pharmacy": "Medical shop",
    "chemist": "Medical shop",
    "kirana": "Kirana shop",
    "kiranashop": "Kirana shop",
    "kiranastore": "Kirana shop",
    "grocery": "Kirana shop",
    "groceryshop": "Kirana shop",
    "generalstore": "Kirana shop",
    "other": "Others",
    "others": "Others",
}


PLAN_CODE_ALIASES = {
    "free": "free_trial_7_days",
    "trial": "free_trial_7_days",
    "freetrial": "free_trial_7_days",
    "freetrial7days": "free_trial_7_days",
    "monthly": "monthly_499",
    "monthly499": "monthly_499",
    "monthly299": "monthly_499",
    "1month": "monthly_499",
    "1monthplan": "monthly_499",
    "yearly": "yearly_4999_machine",
    "annual": "yearly_4999_machine",
    "yearly4999": "yearly_4999_machine",
    "yearly4999machine": "yearly_4999_machine",
    "1year": "yearly_4999_machine",
    "1yearplan": "yearly_4999_machine",
}


def normalize_business_type(value):
    if not value:
        return "Others"

    valid_business_types = {choice for choice, _ in BusinessProfile.BUSINESS_TYPES}
    if value in valid_business_types:
        return value

    normalized = normalize_lookup_value(value)
    return BUSINESS_TYPE_ALIASES.get(normalized, "Others")


def normalize_plan_code(value):
    normalized = normalize_lookup_value(value)
    return PLAN_CODE_ALIASES.get(normalized, value)


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=6, required=False, allow_blank=True)
    phone = serializers.CharField(write_only=True)
    owner_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    business_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    business_address = serializers.CharField(write_only=True, required=False, allow_blank=True)
    gstin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    plan_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    business_type = serializers.ChoiceField(
        choices=BusinessProfile.BUSINESS_TYPES,
        write_only=True,
        required=False,
        default="Others",
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "phone",
            "owner_name",
            "business_name",
            "business_address",
            "gstin",
            "plan_code",
            "business_type",
        )

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        phone = first_present(
            data,
            ("phone", "mobile", "mobile_number", "mobileNumber", "phone_number", "phoneNumber"),
        )
        if phone and not first_present(data, ("phone",)):
            data["phone"] = phone

        if not first_present(data, ("username",)) and phone:
            data["username"] = normalize_local_phone_number(phone)

        field_aliases = {
            "owner_name": ("ownerName", "owner", "full_name", "fullName"),
            "business_name": ("businessName", "shop_name", "shopName", "store_name", "storeName", "name"),
            "business_address": ("businessAddress", "address", "shop_address", "shopAddress"),
            "business_type": ("businessType", "shop_type", "shopType"),
            "plan_code": ("planCode", "subscription_plan", "subscriptionPlan"),
        }

        for field, aliases in field_aliases.items():
            if not first_present(data, (field,)):
                value = first_present(data, aliases)
                if value:
                    data[field] = value

        if first_present(data, ("business_type",)):
            data["business_type"] = normalize_business_type(data["business_type"])

        if first_present(data, ("plan_code",)):
            data["plan_code"] = normalize_plan_code(data["plan_code"])

        return super().to_internal_value(data)

    def validate_username(self, value):
        username = str(value or "").strip()

        if not username:
            return username

        if User.objects.filter(username=username).exists():
            raise serializers.ValidationError("This username is already registered.")

        return username

    def validate_phone(self, value):
        phone = normalize_local_phone_number(value)

        if len(phone) != 10:
            raise serializers.ValidationError("Enter a valid 10 digit phone number.")

        if UserProfile.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("This phone number is already registered.")

        return phone

    def validate_business_type(self, value):
        business_type = normalize_business_type(value)
        valid_business_types = {choice for choice, _ in BusinessProfile.BUSINESS_TYPES}

        if business_type not in valid_business_types:
            return "Others"

        return business_type

    def validate_plan_code(self, value):
        return normalize_plan_code(str(value or "").strip())

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if not attrs.get("username") and attrs.get("phone"):
            attrs["username"] = attrs["phone"]

        if not attrs.get("username"):
            raise serializers.ValidationError({"username": "Username or phone number is required."})

        if User.objects.filter(username=attrs["username"]).exists():
            raise serializers.ValidationError({"username": "This username is already registered."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        owner_name = validated_data.pop("owner_name", "")
        business_name = validated_data.pop("business_name", "")
        business_address = validated_data.pop("business_address", "")
        gstin = validated_data.pop("gstin", "")
        validated_data.pop("plan_code", "")
        business_type = validated_data.pop("business_type", "Others")
        phone = validated_data.pop("phone")
        password = validated_data.pop("password", "")
        user = User(**validated_data)
        if owner_name and not user.first_name:
            user.first_name = owner_name
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()

        business_profile = None
        if business_name:
            business_profile = BusinessProfile.objects.create(
                name=business_name,
                business_type=business_type,
                phone=phone,
                email=user.email,
                address=business_address,
                gstin=gstin,
            )

        UserProfile.objects.create(
            user=user,
            phone=phone,
            business_profile=business_profile,
        )

        return user


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField()


class OTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    otp = serializers.CharField(min_length=4, max_length=6)


class FirebaseLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    phone = serializers.CharField(required=False, allow_blank=True)


class BusinessProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessProfile
        fields = "__all__"


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "code",
            "price",
            "billing_cycle",
            "max_users",
            "max_products",
            "description",
            "is_active",
        )


class BusinessSubscriptionSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    business_phone = serializers.CharField(source="business.phone", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_price = serializers.DecimalField(
        source="plan.price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    billing_cycle = serializers.CharField(source="plan.billing_cycle", read_only=True)
    max_users = serializers.IntegerField(source="plan.max_users", read_only=True)
    max_products = serializers.IntegerField(source="plan.max_products", read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = BusinessSubscription
        fields = (
            "id",
            "business",
            "business_name",
            "business_phone",
            "plan",
            "plan_name",
            "plan_price",
            "billing_cycle",
            "max_users",
            "max_products",
            "status",
            "starts_at",
            "ends_at",
            "trial_ends_at",
            "seats",
            "notes",
            "days_remaining",
            "is_current",
        )


class CategorySerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = "__all__"

    def get_image_url(self, obj):
        return build_full_media_url(obj, self.context.get("request"))

    def validate_parent(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a parent category from your business.")

        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["image"] = data["image_url"]
        return data



class ProductSerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"

    def get_image_url(self, obj):
        return build_full_media_url(obj, self.context.get("request"))

    def validate_category(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a category from your business.")

        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["image"] = data["image_url"]
        return data


class CustomerSerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Customer
        fields = "__all__"


class CreditCustomerSerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CreditCustomer
        fields = (
            "id",
            "business",
            "name",
            "phone",
            "current_balance",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("current_balance", "created_at", "updated_at")


class CreditPaymentSerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    receiptId = serializers.CharField(source="receipt_id", read_only=True)
    paymentMode = serializers.ChoiceField(
        source="payment_mode",
        choices=CreditPayment.PAYMENT_MODES,
        required=False,
    )
    previousBalance = serializers.DecimalField(
        source="previous_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    remainingBalance = serializers.DecimalField(
        source="remaining_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = CreditPayment
        fields = (
            "id",
            "business",
            "customer",
            "customer_name",
            "customer_phone",
            "bill",
            "receiptId",
            "paymentMode",
            "amount",
            "previousBalance",
            "remainingBalance",
            "note",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "receiptId",
            "previousBalance",
            "remainingBalance",
            "created_at",
            "updated_at",
        )

    def validate_business_scope(self, business, customer, bill=None):
        if business.business_type != "Kirana shop":
            raise serializers.ValidationError(
                {"detail": "Credit payments are available only for Kirana shop businesses."},
            )

        if customer.business_id != business.id:
            raise serializers.ValidationError({"customer": "Select a customer from your business."})

        if bill and bill.business_id != business.id:
            raise serializers.ValidationError({"bill": "Select a bill from your business."})

        if bill and bill.credit_customer_id and bill.credit_customer_id != customer.id:
            raise serializers.ValidationError(
                {"bill": "Select a credit bill for this customer."},
            )

    def get_available_balance(self, customer, amount_to_restore=Decimal("0.00")):
        return Decimal(customer.current_balance or 0) + Decimal(amount_to_restore or 0)

    def validate_payment_amount(self, amount, available_balance):
        if Decimal(amount or 0) > available_balance:
            raise serializers.ValidationError(
                {"amount": "Payment amount cannot be greater than customer balance."},
            )

    def validate_customer(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a credit customer from your business.")

        return value

    def validate_bill(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a bill from your business.")

        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        bill = attrs.get("bill", getattr(self.instance, "bill", None))
        amount = attrs.get("amount", getattr(self.instance, "amount", Decimal("0.00")))

        if customer:
            amount_to_restore = (
                Decimal(self.instance.amount or 0)
                if self.instance and self.instance.customer_id == customer.id
                else Decimal("0.00")
            )
            available_balance = self.get_available_balance(customer, amount_to_restore)
            self.validate_payment_amount(amount, available_balance)

        if bill and customer and bill.credit_customer_id and bill.credit_customer_id != customer.id:
            raise serializers.ValidationError({"bill": "Select a credit bill for this customer."})

        return attrs

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")

        return value

    @transaction.atomic
    def create(self, validated_data):
        business = validated_data["business"]
        customer = validated_data["customer"]
        bill = validated_data.get("bill")
        amount = Decimal(validated_data["amount"])
        self.validate_business_scope(business, customer, bill)

        previous_balance = Decimal(customer.current_balance or 0)
        self.validate_payment_amount(amount, previous_balance)
        remaining_balance = max(Decimal("0.00"), previous_balance - amount)

        payment = CreditPayment.objects.create(
            **validated_data,
            previous_balance=previous_balance,
            remaining_balance=remaining_balance,
        )
        if not payment.receipt_id:
            payment.receipt_id = f"PAY-{payment.id:04d}"
            payment.save(update_fields=("receipt_id", "updated_at"))

        customer.current_balance = remaining_balance
        customer.save(update_fields=("current_balance", "updated_at"))
        return payment

    @transaction.atomic
    def update(self, instance, validated_data):
        business = validated_data.pop("business", instance.business)
        old_customer = instance.customer
        restored_old_balance = Decimal(old_customer.current_balance or 0) + Decimal(instance.amount or 0)
        old_customer.current_balance = restored_old_balance
        old_customer.save(update_fields=("current_balance", "updated_at"))

        customer = validated_data.get("customer", old_customer)
        if customer.id == old_customer.id:
            customer.current_balance = restored_old_balance

        bill = validated_data.get("bill", instance.bill)
        amount = Decimal(validated_data.get("amount", instance.amount))
        self.validate_business_scope(business, customer, bill)

        previous_balance = Decimal(customer.current_balance or 0)
        self.validate_payment_amount(amount, previous_balance)
        remaining_balance = max(Decimal("0.00"), previous_balance - amount)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.business = business
        instance.previous_balance = previous_balance
        instance.remaining_balance = remaining_balance
        instance.save()

        customer.current_balance = remaining_balance
        customer.save(update_fields=("current_balance", "updated_at"))

        return instance


class BillItemSerializer(serializers.ModelSerializer):
    image = serializers.CharField(source="image_url", required=False, allow_blank=True)
    quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    line_total = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = BillItem
        fields = (
            "id",
            "product",
            "name",
            "price",
            "quantity",
            "image",
            "line_total",
        )

    def validate_image(self, value):
        return build_absolute_media_url(value, self.context.get("request"))

    def validate_product(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a product from your business.")

        return value


class BillSerializer(serializers.ModelSerializer):
    business = serializers.PrimaryKeyRelatedField(read_only=True)
    items = BillItemSerializer(many=True)
    invoiceId = serializers.CharField(source="invoice_id")
    paymentMode = serializers.ChoiceField(source="payment_mode", choices=Bill.PAYMENT_MODES)
    grandTotal = serializers.DecimalField(
        source="grand_total",
        max_digits=10,
        decimal_places=2,
    )
    isPaid = serializers.BooleanField(source="is_paid", required=False)
    creditCustomer = serializers.PrimaryKeyRelatedField(
        source="credit_customer",
        queryset=CreditCustomer.objects.all(),
        required=False,
        allow_null=True,
    )
    creditCustomerName = serializers.CharField(source="credit_customer.name", read_only=True)
    creditCustomerPhone = serializers.CharField(source="credit_customer.phone", read_only=True)
    paidAmount = serializers.DecimalField(
        source="paid_amount",
        max_digits=10,
        decimal_places=2,
        required=False,
    )
    remainingAmount = serializers.DecimalField(
        source="remaining_amount",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    previousBalance = serializers.DecimalField(
        source="previous_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    totalBalance = serializers.DecimalField(
        source="total_balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Bill
        fields = (
            "id",
            "business",
            "invoiceId",
            "customer",
            "items",
            "paymentMode",
            "subtotal",
            "discount",
            "tax",
            "grandTotal",
            "isPaid",
            "creditCustomer",
            "creditCustomerName",
            "creditCustomerPhone",
            "paidAmount",
            "remainingAmount",
            "previousBalance",
            "totalBalance",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate_customer(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a customer from your business.")

        return value

    def validate_creditCustomer(self, value):
        request = self.context.get("request")
        business = getattr(getattr(request, "user", None), "profile", None)
        business_profile = getattr(business, "business_profile", None)

        if value and business_profile and value.business_id != business_profile.id:
            raise serializers.ValidationError("Select a credit customer from your business.")

        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        payment_mode = attrs.get("payment_mode", getattr(self.instance, "payment_mode", "Cash"))
        credit_customer = attrs.get(
            "credit_customer",
            getattr(self.instance, "credit_customer", None),
        )
        grand_total = attrs.get("grand_total", getattr(self.instance, "grand_total", 0))
        paid_amount = attrs.get("paid_amount", getattr(self.instance, "paid_amount", 0))

        if paid_amount is not None and paid_amount < 0:
            raise serializers.ValidationError({"paidAmount": "Paid amount cannot be negative."})

        if payment_mode == "Credit":
            if not credit_customer:
                raise serializers.ValidationError(
                    {"creditCustomer": "Credit customer is required for credit bills."},
                )
            if Decimal(paid_amount or 0) > Decimal(grand_total or 0):
                raise serializers.ValidationError(
                    {"paidAmount": "Paid amount cannot be greater than bill total."},
                )

        return attrs

    def apply_credit_balance(self, bill, old_credit_customer=None, old_remaining_amount=Decimal("0.00")):
        if old_credit_customer:
            old_credit_customer.current_balance = max(
                Decimal("0.00"),
                Decimal(old_credit_customer.current_balance) - Decimal(old_remaining_amount or 0),
            )
            old_credit_customer.save(update_fields=("current_balance", "updated_at"))

        if bill.payment_mode != "Credit":
            bill.credit_customer = None
            bill.paid_amount = Decimal("0.00")
            bill.remaining_amount = Decimal("0.00")
            bill.previous_balance = Decimal("0.00")
            bill.total_balance = Decimal("0.00")
            bill.is_paid = True
            return

        remaining_amount = max(
            Decimal("0.00"),
            Decimal(bill.grand_total or 0) - Decimal(bill.paid_amount or 0),
        )
        previous_balance = Decimal(bill.credit_customer.current_balance)
        total_balance = previous_balance + remaining_amount

        bill.remaining_amount = remaining_amount
        bill.previous_balance = previous_balance
        bill.total_balance = total_balance
        bill.is_paid = remaining_amount <= 0

        bill.credit_customer.current_balance = total_balance
        bill.credit_customer.save(update_fields=("current_balance", "updated_at"))

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        bill = Bill(**validated_data)
        self.apply_credit_balance(bill)
        bill.save()

        for item_data in items_data:
            BillItem.objects.create(bill=bill, **item_data)

        return bill

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        old_credit_customer = instance.credit_customer if instance.payment_mode == "Credit" else None
        old_remaining_amount = instance.remaining_amount

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        self.apply_credit_balance(instance, old_credit_customer, old_remaining_amount)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                BillItem.objects.create(bill=instance, **item_data)

        return instance
