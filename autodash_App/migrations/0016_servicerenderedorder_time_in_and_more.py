# Generated by Django 5.1.1 on 2024-10-04 17:44

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0015_alter_customuser_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerenderedorder',
            name='time_in',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='servicerenderedorder',
            name='time_out',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='VehicleGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group_name', models.CharField(blank=True, max_length=100, null=True)),
                ('description', models.CharField(blank=True, max_length=255, null=True)),
                ('branches', models.ManyToManyField(related_name='vehiclegroups', to='autodash_App.branch')),
            ],
        ),
        migrations.CreateModel(
            name='CustomerVehicle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('car_plate', models.CharField(blank=True, max_length=100, null=True)),
                ('car_make', models.CharField(blank=True, max_length=100, null=True)),
                ('car_color', models.CharField(blank=True, max_length=100, null=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='vehicles', to='autodash_App.customer')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='vehicle_profile', to=settings.AUTH_USER_MODEL)),
                ('vehicle_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='vehicles', to='autodash_App.vehiclegroup')),
            ],
        ),
        migrations.AddField(
            model_name='service',
            name='vehicle_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='services', to='autodash_App.vehiclegroup'),
        ),
        migrations.AddField(
            model_name='subscription',
            name='vehicle_group',
            field=models.ManyToManyField(blank=True, null=True, to='autodash_App.vehiclegroup'),
        ),
    ]
