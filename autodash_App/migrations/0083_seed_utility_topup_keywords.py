"""Give existing utilities sensible top-up aliases.

A top-up expense is matched to a utility by the utility's own name or one of its
`topup_keywords`. Ghanaian branches write "ECG Prepaid" rather than
"Electricity Prepaid", so without an alias the commonest case would never match.
Only fills in blanks, so anything already set is left alone.
"""
from django.db import migrations


# Matched against the utility's existing name, lower-cased and contained.
DEFAULTS = {
    "electric": "ECG, E.C.G, power, light, prepaid meter",
    "power": "ECG, E.C.G, electricity, light",
    "water": "GWCL, Ghana Water, water bill",
    "fuel": "diesel, petrol, gas",
    "generator": "diesel, petrol, gen",
}


def seed(apps, schema_editor):
    Utility = apps.get_model("autodash_App", "Utility")
    for utility in Utility.objects.all():
        if (utility.topup_keywords or "").strip():
            continue
        name = (utility.name or "").lower()
        for needle, keywords in DEFAULTS.items():
            if needle in name:
                utility.topup_keywords = keywords
                utility.save(update_fields=["topup_keywords"])
                break


def unseed(apps, schema_editor):
    """Only clear what this migration would have written."""
    Utility = apps.get_model("autodash_App", "Utility")
    for utility in Utility.objects.all():
        if utility.topup_keywords in DEFAULTS.values():
            utility.topup_keywords = ""
            utility.save(update_fields=["topup_keywords"])


class Migration(migrations.Migration):

    dependencies = [
        ("autodash_App", "0082_expense_topup_reading_utility_topup_keywords_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
