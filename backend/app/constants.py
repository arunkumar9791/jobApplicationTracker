"""Default lists. Statuses and sources are editable at runtime via settings."""

# Each status has a `kind` that drives KPIs, so renamed or added statuses still count correctly.
#   wishlist  - not applied yet, excluded from application KPIs
#   applied   - submitted, no response yet
#   interview - Screening or later
#   offer     - offer received (incl. accepted)
#   rejected  - closed by the employer
#   closed    - closed for other reasons (withdrawn, ghosted)
STATUS_KINDS = ("wishlist", "applied", "interview", "offer", "rejected", "closed")

DEFAULT_STATUSES = [
    {"name": "Wishlist", "kind": "wishlist", "color": "amber"},
    {"name": "Applied", "kind": "applied", "color": "blue"},
    {"name": "Screening", "kind": "interview", "color": "violet"},
    {"name": "First Round", "kind": "interview", "color": "violet"},
    {"name": "Second Round", "kind": "interview", "color": "violet"},
    {"name": "Final Round", "kind": "interview", "color": "violet"},
    {"name": "Offer", "kind": "offer", "color": "green"},
    {"name": "Accepted", "kind": "offer", "color": "green"},
    {"name": "Rejected", "kind": "rejected", "color": "red"},
    {"name": "Withdrawn", "kind": "closed", "color": "gray"},
    {"name": "Ghosted", "kind": "closed", "color": "gray"},
]

DEFAULT_SOURCES = [
    "Company Site",
    "LinkedIn",
    "Referral",
    "Naukri",
    "Recruiter Call",
    "Email",
    "Resume Sent via Mail",
    "Contacted by Phone",
]

WORK_MODES = ("Onsite", "Hybrid", "Remote")

DEFAULT_SETTINGS = {
    "statuses": DEFAULT_STATUSES,
    "sources": DEFAULT_SOURCES,
    "stale_days": 14,
}
