from django.db import models


class Brand(models.Model):
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=128)
    primary_domain = models.CharField(max_length=253, unique=True)
    tracking_domain = models.CharField(max_length=253, unique=True)
    logo = models.CharField(max_length=500, blank=True, default='')
    favicon = models.CharField(max_length=500, blank=True, default='')
    primary_color = models.CharField(max_length=7, default='#6366f1')
    secondary_color = models.CharField(max_length=7, default='#4f46e5')
    support_email = models.EmailField(max_length=254, default='')
    terms_url = models.CharField(max_length=500, blank=True, default='')
    privacy_url = models.CharField(max_length=500, blank=True, default='')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            Brand.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_default(cls):
        return cls.objects.filter(is_default=True).first() or cls.objects.order_by('id').first()
