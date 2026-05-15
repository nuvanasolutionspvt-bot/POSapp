from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers

from .models import (
    Bill,
    BillItem,
    BusinessProfile,
    BusinessSubscription,
    Category,
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


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    phone = serializers.CharField(write_only=True)
    business_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    business_address = serializers.CharField(write_only=True, required=False, allow_blank=True)
    gstin = serializers.CharField(write_only=True, required=False, allow_blank=True)
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
            "business_name",
            "business_address",
            "gstin",
            "business_type",
        )

    def validate_phone(self, value):
        phone = normalize_local_phone_number(value)

        if len(phone) != 10:
            raise serializers.ValidationError("Enter a valid 10 digit phone number.")

        if UserProfile.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("This phone number is already registered.")

        return phone

    @transaction.atomic
    def create(self, validated_data):
        business_name = validated_data.pop("business_name", "")
        business_address = validated_data.pop("business_address", "")
        gstin = validated_data.pop("gstin", "")
        business_type = validated_data.pop("business_type", "Others")
        phone = validated_data.pop("phone")
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
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


class BillItemSerializer(serializers.ModelSerializer):
    image = serializers.CharField(source="image_url", required=False, allow_blank=True)
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

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        bill = Bill.objects.create(**validated_data)

        for item_data in items_data:
            BillItem.objects.create(bill=bill, **item_data)

        return bill

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                BillItem.objects.create(bill=instance, **item_data)

        return instance
