# Generated by Django 5.1.1 on 2024-11-16 10:06

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('autodash_App', '0024_customervehicle_date_added'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='servicerenderedorder',
            name='discount',
        ),
        migrations.AddField(
            model_name='revenue',
            name='profit',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='service',
            name='commission_rate',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='servicerendered',
            name='commission_amount',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='servicerenderedorder',
            name='discount_type',
            field=models.CharField(choices=[('percentage', 'Percentage'), ('amount', 'Amount')], default='amount', max_length=10),
        ),
        migrations.AddField(
            model_name='servicerenderedorder',
            name='discount_value',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='worker',
            name='daily_commission',
            field=models.FloatField(default=0),
        ),
        migrations.AlterField(
            model_name='servicerendered',
            name='workers',
            field=models.ManyToManyField(blank=True, related_name='services_rendered', to='autodash_App.worker'),
        ),
        migrations.AlterField(
            model_name='servicerenderedorder',
            name='workers',
            field=models.ManyToManyField(blank=True, to='autodash_App.worker'),
        ),
        migrations.CreateModel(
            name='Commission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.FloatField()),
                ('date', models.DateField(auto_now_add=True)),
                ('service_rendered', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='commissions', to='autodash_App.servicerendered')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='commissions', to='autodash_App.worker')),
            ],
        ),
        migrations.CreateModel(
            name='DailyExpenseBudget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('budgeted_amount', models.FloatField()),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_budgets', to='autodash_App.branch')),
            ],
        ),
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.TextField()),
                ('amount', models.FloatField()),
                ('date', models.DateField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expenses', to='autodash_App.branch')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='expenses', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
