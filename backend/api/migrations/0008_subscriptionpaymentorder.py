from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0007_seed_app_subscription_plans"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPaymentOrder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("razorpay_order_id", models.CharField(max_length=120, unique=True)),
                ("razorpay_payment_id", models.CharField(blank=True, max_length=120)),
                ("amount", models.PositiveIntegerField()),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("receipt", models.CharField(max_length=80, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("paid", "Paid"),
                            ("failed", "Failed"),
                        ],
                        default="created",
                        max_length=20,
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_payment_orders",
                        to="api.businessprofile",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment_orders",
                        to="api.subscriptionplan",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]
