# Generated by Django 5.1.2 on 2025-05-02 11:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0046_customersubscription_latest_renewal_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerenderedorder',
            name='comments',
            field=models.TextField(blank=True, null=True),
        ),
    ]
