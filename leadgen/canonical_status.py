"""The canonical, affiliate-visible lead status vocabulary — see
Nexora_Affiliate_Inbound_API_Spec.md §3.1. Deliberately separate from
Lead.status (the internal delivery-state machine routing.py/failover.py/
tasks.py already drive) — Lead.status is untouched by this build; canonical
status is a new, parallel layer answering a different question ("what does
the affiliate see right now"), grouped by lifecycle stage, sourced from
LeadStatusEvent (leadgen/status_sync.py is the only code allowed to write
Lead.canonical_status — never set it directly).

A single flat module (not nested under Lead/LeadStatusEvent) because it's
shared by both those models plus BoxType/LeadBuyer's status_mapping and the
sync task — importing it from either model would be an arbitrary choice.

Confirmed with Paul: full spec vocabulary, qualified_ftd included, one
canonical value per synonym pair (e.g. "chargeback / reversed" -> CHARGEBACK
only) — the alternate name lives in the choice's display label, not as a
second value, so nothing downstream ever has two spellings of one status.
"""

# --- intake / validation ---
NEW = 'new'
TEST = 'test'
DUPLICATE = 'duplicate'
INVALID = 'invalid'
REJECTED = 'rejected'

# --- delivery ---
ROUTED = 'routed'
UNROUTED = 'unrouted'
FAILED = 'failed'

# --- contact cycle (buyer-side, live) ---
PENDING = 'pending'
NO_ANSWER = 'no_answer'
CALLBACK = 'callback'
WRONG_NUMBER = 'wrong_number'
NOT_INTERESTED = 'not_interested'
DO_NOT_CALL = 'do_not_call'

# --- conversion (forex-specific) ---
TEST_FTD = 'test_ftd'
FTD = 'ftd'
QUALIFIED_FTD = 'qualified_ftd'
REDEPOSIT = 'redeposit'
HIGH_VALUE = 'high_value'

# --- terminal / financial ---
APPROVED = 'approved'
CHARGEBACK = 'chargeback'
FRAUD = 'fraud'
EXPIRED = 'expired'

CHOICES = [
    (NEW, 'New'),
    (TEST, 'Test'),
    (DUPLICATE, 'Duplicate'),
    (INVALID, 'Invalid'),
    (REJECTED, 'Rejected'),
    (ROUTED, 'Routed / injected'),
    (UNROUTED, 'Unrouted'),
    (FAILED, 'Failed'),
    (PENDING, 'Pending (with buyer)'),
    (NO_ANSWER, 'No answer'),
    (CALLBACK, 'Callback scheduled'),
    (WRONG_NUMBER, 'Wrong / invalid number'),
    (NOT_INTERESTED, 'Not interested'),
    (DO_NOT_CALL, 'Do not call'),
    (TEST_FTD, 'Test FTD'),
    (FTD, 'FTD (First Time Deposit)'),
    (QUALIFIED_FTD, 'Qualified FTD / billable'),
    (REDEPOSIT, 'Redeposit (FTD+)'),
    (HIGH_VALUE, 'High value / VIP'),
    (APPROVED, 'Approved (billable to affiliate)'),
    (CHARGEBACK, 'Chargeback / reversed'),
    (FRAUD, 'Fraud'),
    (EXPIRED, 'Expired'),
]

VALUES = {value for value, _label in CHOICES}

# Testing-phase equivalents an operator manually walks a lead through
# (see spec §10's acceptance flow: new -> test -> test_ftd). Not enforced
# anywhere yet — informational grouping for the future operator UI (Phase 6
# of this spec) to default-suggest the right next status in TESTING.
TESTING_PHASE_STATUSES = {TEST, TEST_FTD}
