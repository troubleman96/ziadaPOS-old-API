from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_add_product_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='is_global',
            field=models.BooleanField(
                default=False,
                help_text='Pre-seeded global category visible to all users.',
            ),
        ),
    ]
