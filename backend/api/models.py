from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from PIL import Image, ImageOps


def optimize_uploaded_image(image_field):
    if not image_field:
        return

    try:
        image_path = image_field.path
    except (NotImplementedError, ValueError):
        return

    try:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            save_kwargs = {"optimize": True}
            image_format = image.format or "JPEG"

            if image_format.upper() in {"JPEG", "JPG"}:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                save_kwargs["quality"] = 75
                image_format = "JPEG"

            image.save(image_path, format=image_format, **save_kwargs)
    except OSError:
        return


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BusinessProfile(TimeStampedModel):
    BUSINESS_TYPES = (
        ("Food shop", "Food shop"),
        ("Medical shop", "Medical shop"),
        ("Others", "Others"),
    )

    name = models.CharField(max_length=150)
    business_type = models.CharField(
        max_length=30,
        choices=BUSINESS_TYPES,
        default="Others",
    )
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    gstin = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return self.name


class SubscriptionPlan(TimeStampedModel):
    BILLING_CYCLES = (
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    )

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=40, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    billing_cycle = models.CharField(
        max_length=20,
        choices=BILLING_CYCLES,
        default="monthly",
    )
    max_users = models.PositiveIntegerField(default=1)
    max_products = models.PositiveIntegerField(default=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("price", "name")

    def __str__(self):
        return self.name


class BusinessSubscription(TimeStampedModel):
    STATUSES = (
        ("trial", "Trial"),
        ("active", "Active"),
        ("past_due", "Past due"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    )

    business = models.OneToOneField(
        BusinessProfile,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(max_length=20, choices=STATUSES, default="trial")
    starts_at = models.DateField(default=timezone.localdate)
    ends_at = models.DateField()
    trial_ends_at = models.DateField(null=True, blank=True)
    seats = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("ends_at", "business__name")

    @property
    def is_current(self):
        return self.status in {"trial", "active"} and self.ends_at >= timezone.localdate()

    @property
    def days_remaining(self):
        return (self.ends_at - timezone.localdate()).days

    def __str__(self):
        return f"{self.business} - {self.plan}"


class SubscriptionPaymentOrder(TimeStampedModel):
    STATUSES = (
        ("created", "Created"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    )

    business = models.ForeignKey(
        BusinessProfile,
        on_delete=models.CASCADE,
        related_name="subscription_payment_orders",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    razorpay_order_id = models.CharField(max_length=120, unique=True)
    razorpay_payment_id = models.CharField(max_length=120, blank=True)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    receipt = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="created")

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.razorpay_order_id} - {self.plan}"


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=20, unique=True)
    business_profile = models.ForeignKey(
        BusinessProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )

    def __str__(self):
        return f"{self.user.username} - {self.phone}"


class LoginOTP(TimeStampedModel):
    PURPOSES = (
        ("login", "Login"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_otps")
    phone = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSES, default="login")
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_verified(self):
        return self.verified_at is not None

    def __str__(self):
        return f"{self.phone} OTP for {self.purpose}"


class Category(TimeStampedModel):
    business = models.ForeignKey(
        BusinessProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categories",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    display_order = models.PositiveIntegerField(default=1)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    image = models.ImageField(upload_to="categories/", blank=True, null=True)

    class Meta:
        ordering = ("display_order", "name")
        verbose_name_plural = "categories"
        constraints = (
            models.UniqueConstraint(
                fields=("business", "name"),
                name="unique_category_name_per_business",
            ),
            models.UniqueConstraint(
                fields=("business", "code"),
                name="unique_category_code_per_business",
            ),
        )

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        optimize_uploaded_image(self.image)


class Product(TimeStampedModel):
    UNIT_TYPES = (
        ("pc", "Piece"),
        ("kg", "Kilogram"),
        ("g", "Gram"),
        ("l", "Litre"),
        ("ml", "Millilitre"),
        ("plate", "Plate"),
    )

    business = models.ForeignKey(
        BusinessProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=180)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPES, default="pc")
    barcode = models.CharField(max_length=80, blank=True, null=True)
    description = models.TextField(blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    image = models.ImageField(upload_to="products/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        optimize_uploaded_image(self.image)


class Customer(TimeStampedModel):
    CUSTOMER_TYPES = (
        ("Retail", "Retail"),
        ("Wholesale", "Wholesale"),
    )

    business = models.ForeignKey(
        BusinessProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="customers",
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField()
    city = models.CharField(max_length=80)
    pin_code = models.CharField(max_length=12, blank=True)
    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPES,
        default="Retail",
    )
    opening_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gstin = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("full_name",)

    def __str__(self):
        return self.full_name


class Bill(TimeStampedModel):
    PAYMENT_MODES = (
        ("Cash", "Cash"),
        ("UPI", "UPI"),
        ("Card", "Card"),
    )

    business = models.ForeignKey(
        BusinessProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bills",
    )
    invoice_id = models.CharField(max_length=30)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
    )
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES, default="Cash")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("business", "invoice_id"),
                name="unique_invoice_per_business",
            ),
        )

    def __str__(self):
        return self.invoice_id


class BillItem(TimeStampedModel):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bill_items",
    )
    name = models.CharField(max_length=180)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    image_url = models.TextField(blank=True)

    @property
    def line_total(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.name} x {self.quantity}"
