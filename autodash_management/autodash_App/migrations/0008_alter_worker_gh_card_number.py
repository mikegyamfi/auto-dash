# Generated by Django 5.1.1 on 2024-10-01 13:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0007_alter_customuser_username'),
    ]

    operations = [
        migrations.AlterField(
            model_name='worker',
            name='gh_card_number',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]