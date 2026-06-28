"""Phase 95-12 — Domain Analyst Subscriber package.

Single process subscribing all 12 long-lived domain analysts (CONTEXT §F)
to the EventBus MACRO_RELEASE stream, filtered per agent by
``payload.affected_domains contains <domain_slug>``. Keeps container
count flat (1 service for 12 agents) — see plan 95-12 spec.

Ships as docker-compose sibling service per
``feedback_mgmt_commands_need_compose_service``.
"""

from agents.domain_analyst_subscriber.subscriber import (
    DEBOUNCE_SECONDS,
    DOMAIN_SLUGS,
    DomainAnalystSubscriber,
    load_analysts,
)

__all__ = [
    "DomainAnalystSubscriber",
    "DEBOUNCE_SECONDS",
    "DOMAIN_SLUGS",
    "load_analysts",
]
