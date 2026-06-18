from django.db import migrations, models


def populate_receipt_ids(apps, schema_editor):
    CreditPayment = apps.get_model("api", "CreditPayment")

    for payment in CreditPayment.objects.filter(receipt_id="").order_by("id"):
        payment.receipt_id = f"PAY-{payment.id:04d}"
        payment.save(update_fields=("receipt_id",))


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0012_credit_billing"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditpayment",
            name="payment_mode",
            field=models.CharField(
                choices=[("Cash", "Cash"), ("UPI", "UPI"), ("Card", "Card")],
                default="Cash",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="creditpayment",
            name="previous_balance",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="creditpayment",
            name="receipt_id",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="creditpayment",
            name="remaining_balance",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.RunPython(populate_receipt_ids, migrations.RunPython.noop),
    ]
