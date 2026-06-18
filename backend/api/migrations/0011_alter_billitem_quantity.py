from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0010_add_kirana_business_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="billitem",
            name="quantity",
            field=models.DecimalField(decimal_places=3, default=1, max_digits=10),
        ),
    ]
