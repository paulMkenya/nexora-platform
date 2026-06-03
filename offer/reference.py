"""Standard reference data for offers — categories (verticals) and traffic
sources. Consumed by the idempotent seed data migrations and safe to import
elsewhere. Editing these lists and re-running the seed migrations only adds
missing rows; it never deletes or renames operator-created rows.
"""

# (name, is_adult) — the comprehensive set of standard affiliate verticals.
STANDARD_CATEGORIES = [
    ('Finance', False),
    ('Insurance', False),
    ('Crypto / Trading', False),
    ('iGaming / Betting', False),
    ('Sweepstakes', False),
    ('Nutra / Health', False),
    ('Dating', False),
    ('E-commerce', False),
    ('Mobile Apps / Games', False),
    ('Software / SaaS', False),
    ('Education', False),
    ('Travel', False),
    ('Telecom', False),
    ('Lead Generation', False),
    ('Adult', True),
]

# The standard affiliate traffic-source taxonomy.
STANDARD_TRAFFIC_SOURCES = [
    'SEO',
    'Display',
    'Native',
    'Push',
    'Pop',
    'Social Paid',
    'Social Organic',
    'Email',
    'Search / PPC',
    'Influencer',
    'Incent',
    'In-App',
    'Video',
    'Contextual',
    'Direct',
]
