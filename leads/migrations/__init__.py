def import_backfill():
    """Run the 0002 data-migration backfill against the live app registry.

    Exposed for tests so the backfill logic can be exercised directly without
    re-running the whole migration graph.
    """
    import importlib

    from django.apps import apps

    module = importlib.import_module('leads.migrations.0002_backfill_leads')
    module.backfill(apps, None)
