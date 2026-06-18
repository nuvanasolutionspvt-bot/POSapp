from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_alter_billitem_quantity"),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditCustomer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=150)),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("current_balance", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credit_customers",
                        to="api.businessprofile",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AlterField(
            model_name="bill",
            name="payment_mode",
            field=models.CharField(
                choices=[
                    ("Cash", "Cash"),
                    ("UPI", "UPI"),
                    ("Card", "Card"),
                    ("Credit", "Credit"),
                ],
                default="Cash",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="bill",
            name="credit_customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="bills",
                to="api.creditcustomer",
            ),
        ),
        migrations.AddField(
            model_name="bill",
            name="paid_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="bill",
            name="previous_balance",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="bill",
            name="remaining_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="bill",
            name="total_balance",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.CreateModel(
            name="CreditPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("note", models.TextField(blank=True)),
                (
                    "bill",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="credit_payments",
                        to="api.bill",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credit_payments",
                        to="api.businessprofile",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payments",
                        to="api.creditcustomer",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]
