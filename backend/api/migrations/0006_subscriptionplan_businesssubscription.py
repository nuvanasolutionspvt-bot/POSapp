from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_default_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("api", "SubscriptionPlan")
    plans = [
        {
            "name": "Starter",
            "code": "starter",
            "price": "499.00",
            "billing_cycle": "monthly",
            "max_users": 1,
            "max_products": 250,
            "description": "For new shops starting with billing, products, and basic reports.",
        },
        {
            "name": "Growth",
            "code": "growth",
            "price": "999.00",
            "billing_cycle": "monthly",
            "max_users": 3,
            "max_products": 1000,
            "description": "For growing shops with more products and multiple staff users.",
        },
        {
            "name": "Pro",
            "code": "pro",
            "price": "1999.00",
            "billing_cycle": "monthly",
            "max_users": 10,
            "max_products": 5000,
            "description": "For larger shops that need higher limits and full reporting.",
        },
    ]

    for plan in plans:
        SubscriptionPlan.objects.get_or_create(code=plan["code"], defaults=plan)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_alter_category_gst_rate_alter_product_gst_rate"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120, unique=True)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "billing_cycle",
                    models.CharField(
                        choices=[("monthly", "Monthly"), ("quarterly", "Quarterly"), ("yearly", "Yearly")],
                        default="monthly",
                        max_length=20,
                    ),
                ),
                ("max_users", models.PositiveIntegerField(default=1)),
                ("max_products", models.PositiveIntegerField(default=100)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ("price", "name"),
            },
        ),
        migrations.CreateModel(
            name="BusinessSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("trial", "Trial"),
                            ("active", "Active"),
                            ("past_due", "Past due"),
                            ("expired", "Expired"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="trial",
                        max_length=20,
                    ),
                ),
                ("starts_at", models.DateField(default=django.utils.timezone.localdate)),
                ("ends_at", models.DateField()),
                ("trial_ends_at", models.DateField(blank=True, null=True)),
                ("seats", models.PositiveIntegerField(default=1)),
                ("notes", models.TextField(blank=True)),
                (
                    "business",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription",
                        to="api.businessprofile",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subscriptions",
                        to="api.subscriptionplan",
                    ),
                ),
            ],
            options={
                "ordering": ("ends_at", "business__name"),
            },
        ),
        migrations.RunPython(create_default_plans, migrations.RunPython.noop),
    ]
