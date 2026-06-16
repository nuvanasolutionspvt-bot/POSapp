from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0009_scope_business_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="businessprofile",
            name="business_type",
            field=models.CharField(
                choices=[
                    ("Food shop", "Food shop"),
                    ("Medical shop", "Medical shop"),
                    ("Kirana shop", "Kirana shop"),
                    ("Others", "Others"),
                ],
                default="Others",
                max_length=30,
            ),
        ),
    ]
