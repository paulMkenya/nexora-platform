"""Template filters for displaying stored country codes as flag + name."""
from django import template

from user_profile.geo import country_display, country_name, iso_to_flag

register = template.Library()


@register.filter(name='country_flag')
def country_flag(code):
    return iso_to_flag(code)


@register.filter(name='country_name')
def country_name_filter(code):
    return country_name(code)


@register.filter(name='country_display')
def country_display_filter(code):
    return country_display(code)
