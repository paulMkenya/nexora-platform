from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_profile', '0008_profile_archive_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='theme_preference',
            field=models.CharField(
                choices=[('dark', 'Dark'), ('light', 'Light')],
                default='dark',
                max_length=5,
            ),
        ),
    ]
