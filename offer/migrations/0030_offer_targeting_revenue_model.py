from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0029_standardize_country'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='category',
            options={'ordering': ('name',), 'verbose_name_plural': 'Categories'},
        ),
        migrations.AddField(
            model_name='category',
            name='is_adult',
            field=models.BooleanField(
                default=False,
                help_text='Adult / restricted vertical.',
            ),
        ),
        migrations.AddField(
            model_name='offer',
            name='revenue_model',
            field=models.CharField(
                default='CPA',
                max_length=16,
                choices=[
                    ('CPA', 'CPA — Cost Per Action'),
                    ('CPL', 'CPL — Cost Per Lead'),
                    ('CPS', 'CPS — Cost Per Sale'),
                    ('CPI', 'CPI — Cost Per Install'),
                    ('CPC', 'CPC — Cost Per Click'),
                    ('RevShare', 'RevShare — Revenue Share'),
                    ('Hybrid', 'Hybrid — CPA + RevShare'),
                ],
                help_text='Pricing model affiliates are paid under for this offer.',
            ),
        ),
        migrations.AddField(
            model_name='offer',
            name='country_mode',
            field=models.CharField(
                default='ALLOW_ALL',
                max_length=12,
                choices=[
                    ('ALLOW_ALL', 'Global — accept all countries'),
                    ('ALLOW_LIST', 'Allow list — only listed countries'),
                    ('BLOCK_LIST', 'Block list — all except listed countries'),
                ],
                help_text='How the country list below is applied.',
            ),
        ),
    ]
