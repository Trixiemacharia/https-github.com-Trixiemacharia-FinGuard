from apps.wallets.throttles import _DefaultedRate


class AssistantThrottle(_DefaultedRate):
    """Per-user limit on questions (each may call the language provider twice)."""

    scope = "assistant"
    default_rate = "10/min"


class AssistantPollThrottle(_DefaultedRate):
    scope = "assistant_poll"
    default_rate = "120/min"
