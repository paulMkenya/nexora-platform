from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mmp', '0002_seed_vendors'),
        ('offer', '0023_advertiserpostbackkey'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='mmp',
            field=models.ForeignKey(
                blank=True, default=None, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='offers',
                to='mmp.mmp',
            ),
        ),
        migrations.AddField(
            model_name='offer',
            name='mmp_app_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='offer',
            name='mmp_extra',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
