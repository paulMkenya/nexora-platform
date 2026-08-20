"""Standard reference data for offers — categories (verticals) and traffic
sources. Consumed by the idempotent seed data migrations and safe to import
elsewhere. Editing these lists and re-running the seed migrations only adds
missing rows; it never deletes or renames operator-created rows.
"""

# (name, is_adult) — the comprehensive set of standard affiliate verticals.
#
# ⚠️ KEEP THIS TUPLE SHAPE. offer/migrations/0031_seed_categories.py imports this
# list at RUN time rather than freezing a copy, and unpacks exactly two values.
# Adding a third element here would break that migration on every fresh database
# — including every `pytest --create-db` run. The machine-readable slug lives in
# CATEGORY_SLUGS below for that reason, not as a third element.
#
# Adding a name here is safe and additive: the seed matches on name, creates
# what is missing, and never renames or deletes an operator-created row.
STANDARD_CATEGORIES = [
    # --- financial: Nexora's core business, so listed first and in most detail
    ('Finance', False),
    ('Forex', False),
    ('Crypto / Trading', False),
    ('Binary Options', False),
    ('CFD / Commodities', False),
    ('Stocks / Investments', False),
    ('Wealth / Make Money Online', False),
    ('Debt / Loans', False),
    ('Mortgages', False),
    ('Insurance', False),
    ('Banking / Cards', False),
    # --- gambling & gaming
    ('iGaming / Betting', False),
    ('Casino', False),
    ('Sports Betting', False),
    ('Poker', False),
    ('Lottery', False),
    ('Mobile Apps / Games', False),
    # --- health & lifestyle
    ('Nutra / Health', False),
    ('Weight Loss', False),
    ('Beauty / Skincare', False),
    ('Fitness', False),
    ('CBD', False),
    ('Pharma', False),
    # --- consumer services
    ('Home Improvement', False),
    ('Solar / Green Energy', False),
    ('Utilities / Energy', False),
    ('Home Security', False),
    ('Real Estate', False),
    ('Automotive', False),
    ('Legal', False),
    ('Jobs / Employment', False),
    ('Charity / Donations', False),
    # --- digital & retail
    ('E-commerce', False),
    ('Software / SaaS', False),
    ('Antivirus / VPN', False),
    ('Web Hosting', False),
    ('Streaming / Entertainment', False),
    ('Education', False),
    ('Travel', False),
    ('Telecom', False),
    ('Mobile Content / VAS', False),
    ('Sweepstakes', False),
    ('Surveys', False),
    ('Lead Generation', False),
    ('Pets', False),
    ('Fashion', False),
    # --- restricted
    ('Dating', False),
    ('Adult', True),
]

# Category name -> the MACHINE value that travels on the wire.
#
# Two different things, deliberately kept apart. The name is what an operator
# reads ("Crypto / Trading"); the slug is what is stored on Lead.vertical and
# forwarded to a buyer — Hypernet maps vertical onto its `funnel`, so this
# string lands in the buyer's own reporting and they optimise on it.
#
# ⚠️ SLUGS ARE A WIRE CONTRACT. Live desperados traffic already carries
# `crypto`, and that is why 'Crypto / Trading' maps to 'crypto' rather than the
# slugified name. Changing an existing slug silently re-labels a buyer's
# reporting mid-campaign; add new ones freely, but treat these as append-only.
CATEGORY_SLUGS = {
    'Finance': 'finance',
    'Forex': 'forex',
    'Crypto / Trading': 'crypto',
    'Binary Options': 'binary-options',
    'CFD / Commodities': 'cfd',
    'Stocks / Investments': 'stocks',
    'Wealth / Make Money Online': 'mmo',
    'Debt / Loans': 'loans',
    'Mortgages': 'mortgages',
    'Insurance': 'insurance',
    'Banking / Cards': 'banking',
    'iGaming / Betting': 'igaming',
    'Casino': 'casino',
    'Sports Betting': 'sports-betting',
    'Poker': 'poker',
    'Lottery': 'lottery',
    'Mobile Apps / Games': 'mobile-apps',
    'Nutra / Health': 'nutra',
    'Weight Loss': 'weight-loss',
    'Beauty / Skincare': 'beauty',
    'Fitness': 'fitness',
    'CBD': 'cbd',
    'Pharma': 'pharma',
    'Home Improvement': 'home-improvement',
    'Solar / Green Energy': 'solar',
    'Utilities / Energy': 'utilities',
    'Home Security': 'home-security',
    'Real Estate': 'real-estate',
    'Automotive': 'automotive',
    'Legal': 'legal',
    'Jobs / Employment': 'jobs',
    'Charity / Donations': 'charity',
    'E-commerce': 'ecommerce',
    'Software / SaaS': 'saas',
    'Antivirus / VPN': 'antivirus',
    'Web Hosting': 'hosting',
    'Streaming / Entertainment': 'streaming',
    'Education': 'education',
    'Travel': 'travel',
    'Telecom': 'telecom',
    'Mobile Content / VAS': 'mobile-vas',
    'Sweepstakes': 'sweepstakes',
    'Surveys': 'surveys',
    'Lead Generation': 'leadgen',
    'Pets': 'pets',
    'Fashion': 'fashion',
    'Dating': 'dating',
    'Adult': 'adult',
}

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
