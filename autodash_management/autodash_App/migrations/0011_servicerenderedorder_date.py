# Generated by Django 5.1.1 on 2024-10-01 14:16

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0010_revenue_discount_revenue_final_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerenderedorder',
            name='date',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
