from django.db import migrations


def seed_app_subscription_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("api", "SubscriptionPlan")
    plans = [
        {
            "name": "Free Trial",
            "code": "free_trial_7_days",
            "price": "0.00",
            "billing_cycle": "monthly",
            "max_users": 1,
            "max_products": 50,
            "description": "7 days free trial for billing, products, customers, and reports.",
            "is_active": True,
        },
        {
            "name": "1 Month Plan",
            "code": "monthly_499",
            "price": "499.00",
            "billing_cycle": "monthly",
            "max_users": 3,
            "max_products": 1000,
            "description": "1 month POS subscription for billing, products, customers, and reports.",
            "is_active": True,
        },
        {
            "name": "1 Year Plan",
            "code": "yearly_4999_machine",
            "price": "4999.00",
            "billing_cycle": "yearly",
            "max_users": 10,
            "max_products": 5000,
            "description": "1 year POS subscription with billing machine included.",
            "is_active": True,
        },
    ]

    for plan in plans:
        SubscriptionPlan.objects.update_or_create(
            code=plan["code"],
            defaults=plan,
        )

    SubscriptionPlan.objects.filter(code__in=["starter", "growth", "pro"]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0006_subscriptionplan_businesssubscription"),
    ]

    operations = [
        migrations.RunPython(seed_app_subscription_plans, migrations.RunPython.noop),
    ]
