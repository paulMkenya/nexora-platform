"""Report the DELIVERY side of a lead's life into canonical_status.

WHY THIS EXISTS. canonical_status is the field the affiliate doc points a
traffic source at, and it was only ever written by two things: a buyer status
report and an operator flip. Every lead that had not yet reached a buyer — and
every lead that never would — therefore read as an empty string forever.

That empty string was doing two incompatible jobs. On a lead in flight it meant
"nothing has happened yet"; on a lead whose buyer refused it five times it
meant "this is over, nobody is coming". A source polling
`GET /api/leads?updated_since=...` could not tell those apart from the field we
told them to read, and reasonably concluded our reporting was broken. Lead 98
was the example that surfaced it: capacity-refused at Badboys, retried,
exhausted — and reported as blank.

So the delivery state machine now reports into the same canonical vocabulary
the buyer reports into, through the same audit trail (LeadStatusEvent), using
the SOURCE_SYSTEM value that has existed unused since the table was created.

THE ONE RULE THAT MAKES THIS SAFE: the buyer outranks us, always. Once a
buyer-sourced event has APPLIED to a lead, nothing here ever writes again. That
is not a nicety — `no_answer` is the buyer's verdict on a person, and a redrive
setting Lead.status back to `new` must never be allowed to overwrite it with
`new`. The guard is a query against the event table rather than an inspection
of the current canonical value, because the current value cannot tell you who
put it there.
"""
import logging

from . import canonical_status
from .models import Lead, LeadStatusEvent
from .status_sync import apply_status_change

logger = logging.getLogger(__name__)


# Lead.status (our internal delivery machine) -> canonical_status (what the
# affiliate reads). Deliberately NOT exhaustive; see the two omissions below.
DELIVERY_CANONICAL = {
    Lead.STATUS_NEW: canonical_status.NEW,
    Lead.STATUS_INJECTED: canonical_status.ROUTED,
    Lead.STATUS_DUPLICATE: canonical_status.DUPLICATE,
    Lead.STATUS_REJECTED: canonical_status.REJECTED,
    Lead.STATUS_FAILED: canonical_status.FAILED,
    Lead.STATUS_UNROUTED: canonical_status.UNROUTED,
}

# STATUS_QUARANTINED is absent on purpose. It means "we do not know whether the
# buyer took this lead" (an ambiguous timeout or 5xx). Reporting FAILED would
# assert an outcome nobody observed, and the lead may well be live in the
# buyer's system. It keeps whatever canonical status it already had and waits
# for the human that STATUS_QUARANTINED exists to summon.
#
# STATUS_DEPOSIT is absent because it is the buyer's word, not ours — by the
# time it is set a buyer event has applied and the guard below would skip us
# anyway. Listing it would imply this module has an opinion about conversions.

# Which of the above are worth waking an affiliate's postback endpoint for.
# A terminal delivery failure is ACTIONABLE — it is the difference between "we
# are working on it" and "send this lead somewhere else". Progress through the
# happy path is not: a source that just POSTed a lead does not need a callback
# telling them we received it, and `routed` is superseded by the buyer's first
# real status minutes later.
NOTIFYING = frozenset({
    canonical_status.DUPLICATE,
    canonical_status.REJECTED,
    canonical_status.FAILED,
    canonical_status.UNROUTED,
})


def buyer_has_spoken(lead):
    """True once a buyer-sourced event has APPLIED to this lead.

    `applied` matters: a TESTING-phase buyer report is recorded but never
    touches canonical_status, so it must not lock the delivery layer out of a
    field the buyer is not yet allowed to write.
    """
    return LeadStatusEvent.objects.filter(
        lead=lead, source=LeadStatusEvent.SOURCE_BUYER, applied=True,
    ).exists()


def report(lead_pk):
    """Bring canonical_status in line with this lead's delivery state.

    Safe to call from anywhere, any number of times: apply_status_change is
    already a no-op when the status would not change, and an unmapped delivery
    state or a lead the buyer has spoken about returns without writing.

    Never raises into its caller. Every call site is a live injection path, and
    a reporting failure must not be able to fail a delivery or, worse, cause a
    retry that double-sends a lead to a buyer.
    """
    try:
        lead = Lead.objects.filter(pk=lead_pk).only('pk', 'status', 'canonical_status').first()
        if lead is None:
            return None

        to_status = DELIVERY_CANONICAL.get(lead.status)
        if to_status is None or lead.canonical_status == to_status:
            return None
        if buyer_has_spoken(lead):
            return None

        return apply_status_change(
            lead, to_status,
            source=LeadStatusEvent.SOURCE_SYSTEM,
            raw_payload={'delivery_status': lead.status},
            notify=to_status in NOTIFYING,
        )
    except Exception:
        logger.exception('delivery_status.report failed for lead #%s', lead_pk)
        return None
