from django.db import migrations


def update_monthly_plan_price(apps, schema_editor):
    SubscriptionPlan = apps.get_model("api", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(code="monthly_499").update(
        price="299.00",
        description="1 month POS subscription for billing, products, customers, and reports.",
    )


def restore_monthly_plan_price(apps, schema_editor):
    SubscriptionPlan = apps.get_model("api", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(code="monthly_499").update(price="499.00")


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0013_creditpayment_payment_mode_and_more"),
    ]

    operations = [
        migrations.RunPython(update_monthly_plan_price, restore_monthly_plan_price),
    ]
