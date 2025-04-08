# Generated by Django 5.1.2 on 2025-03-19 11:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0039_alter_servicerenderedorder_customer'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerenderedorder',
            name='cash_paid_amount',
            field=models.FloatField(blank=True, default=0.0, null=True),
        ),
        migrations.AddField(
            model_name='servicerenderedorder',
            name='loyalty_used_amount',
            field=models.FloatField(blank=True, default=0.0, null=True),
        ),
        migrations.AddField(
            model_name='servicerenderedorder',
            name='subscription_used_amount',
            field=models.FloatField(blank=True, default=0.0, null=True),
        ),
    ]
