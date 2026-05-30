def device_type(ua_string: str) -> str:
    """Return 'mobile', 'tablet', or 'desktop' from a User-Agent string."""
    if not ua_string:
        return 'desktop'

    try:
        import user_agents
        ua = user_agents.parse(ua_string)
        if ua.is_tablet:
            return 'tablet'
        if ua.is_mobile:
            return 'mobile'
        return 'desktop'
    except ImportError:
        pass

    # Fallback heuristic when user_agents library is unavailable.
    lower = ua_string.lower()
    if any(t in lower for t in ('ipad', 'tablet', 'kindle', 'playbook')):
        return 'tablet'
    if any(t in lower for t in ('mobile', 'android', 'iphone', 'ipod', 'windows phone')):
        return 'mobile'
    return 'desktop'
