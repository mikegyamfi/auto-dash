# Generated by Django 5.1.2 on 2025-02-17 10:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0035_workercategory_customer_customer_group_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='expense_category',
            field=models.CharField(blank=True, choices=[('Statutory', 'Statutory'), ('Variable', 'Variable')], max_length=250, null=True),
        ),
    ]
