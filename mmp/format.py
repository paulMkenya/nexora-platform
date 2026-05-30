"""
Pure functions for formatting MMP click URLs from template + context.

Supported macros in click_template:
  {click_id}    — the Nexora tracker click UUID
  {app_id}      — offer.mmp_app_id
  {affiliate_id} — affiliate user PK (string)
  {offer_id}    — offer PK (string)
"""
from typing import Dict


def format_click_url(template: str, ctx: Dict[str, str]) -> str:
    """Replace all known macros in *template* with values from *ctx*."""
    result = template
    for key, value in ctx.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def build_mmp_click_url(click_template: str, click_id: str, app_id: str,
                         affiliate_id: str, offer_id: str) -> str:
    return format_click_url(click_template, {
        'click_id': click_id,
        'app_id': app_id,
        'affiliate_id': str(affiliate_id),
        'offer_id': str(offer_id),
    })
