# Generated by Django 5.1.1 on 2024-10-03 14:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0013_servicerenderedorder_amount_paid_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='servicerenderedorder',
            name='amount_paid',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='servicerenderedorder',
            name='final_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
