from django.db import models


class BrandScopedQuerySet(models.QuerySet):
    def for_brand(self, brand):
        return self.filter(brand=brand)


class BrandScopedManager(models.Manager):
    def get_queryset(self):
        return BrandScopedQuerySet(self.model, using=self._db)

    def for_brand(self, brand):
        return self.get_queryset().for_brand(brand)
