from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0008_subscriptionpaymentorder"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="categories",
                to="api.businessprofile",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="products",
                to="api.businessprofile",
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="customers",
                to="api.businessprofile",
            ),
        ),
        migrations.AddField(
            model_name="bill",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bills",
                to="api.businessprofile",
            ),
        ),
        migrations.AlterField(
            model_name="category",
            name="name",
            field=models.CharField(max_length=120),
        ),
        migrations.AlterField(
            model_name="category",
            name="code",
            field=models.CharField(max_length=30),
        ),
        migrations.AlterField(
            model_name="product",
            name="barcode",
            field=models.CharField(blank=True, max_length=80, null=True),
        ),
        migrations.AlterField(
            model_name="bill",
            name="invoice_id",
            field=models.CharField(max_length=30),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                fields=("business", "name"),
                name="unique_category_name_per_business",
            ),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                fields=("business", "code"),
                name="unique_category_code_per_business",
            ),
        ),
        migrations.AddConstraint(
            model_name="bill",
            constraint=models.UniqueConstraint(
                fields=("business", "invoice_id"),
                name="unique_invoice_per_business",
            ),
        ),
    ]
