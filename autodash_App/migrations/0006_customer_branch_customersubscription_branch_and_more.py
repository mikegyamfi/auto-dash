# Generated by Django 5.1.1 on 2024-10-01 09:59

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0005_customuser_approved_alter_customuser_email_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='customers', to='autodash_App.branch'),
        ),
        migrations.AddField(
            model_name='customersubscription',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='subscriptions', to='autodash_App.branch'),
        ),
        migrations.AddField(
            model_name='loyaltytransaction',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='loyalty_transactions', to='autodash_App.branch'),
        ),
        migrations.CreateModel(
            name='AdminAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='admin_profile', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
