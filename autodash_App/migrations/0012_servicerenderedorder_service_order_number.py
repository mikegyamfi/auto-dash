# Generated by Django 5.1.1 on 2024-10-01 14:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0011_servicerenderedorder_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerenderedorder',
            name='service_order_number',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
