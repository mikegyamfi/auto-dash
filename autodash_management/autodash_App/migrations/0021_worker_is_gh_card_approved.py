# Generated by Django 5.1.1 on 2024-10-04 21:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0020_alter_revenue_amount_alter_revenue_discount_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='worker',
            name='is_gh_card_approved',
            field=models.BooleanField(default=False),
        ),
    ]
