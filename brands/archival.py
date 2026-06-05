"""Soft-delete (archive) state shared by Profile, Advertiser and Brand.

Archiving is a **reversible** soft delete. It only flips a flag and stamps
who/when — it never touches financial history (conversions, payout requests,
wallet transactions are all retained). Restoring clears the flag.

The single visibility rule everywhere: active list/visibility queries exclude
archived rows with ``.filter(is_archived=False)`` (or the model's ``is_active``
helper); the Archived home is the only surface that selects ``is_archived=True``.

Permanent (hard) deletion is a separate, guarded operation — see
``brands.lifecycle`` for the financial-emptiness eligibility check.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Archivable(models.Model):
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        abstract = True

    def archive(self, by=None):
        """Soft-delete: stamp the actor/time and remove from active surfaces."""
        self.is_archived = True
        self.archived_at = timezone.now()
        self.archived_by = by
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by'])

    def restore(self):
        """Reverse an archive — bring the entity back to active surfaces."""
        self.is_archived = False
        self.archived_at = None
        self.archived_by = None
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by'])
