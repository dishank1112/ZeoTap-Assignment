from __future__ import annotations

from dataclasses import dataclass

from app.schemas.signal import ComponentType, SignalResponse


@dataclass(frozen=True)
class AlertDecision:
    alert_type: str
    priority: str
    routing_key: str
    summary: str


class AlertingStrategy:
    alert_type = "STANDARD_ALERT"
    priority = "P3"
    routing_key = "platform-triage"

    def decide(self, signal: SignalResponse) -> AlertDecision:
        return AlertDecision(
            alert_type=self.alert_type,
            priority=self.priority,
            routing_key=self.routing_key,
            summary=(
                f"{self.priority} {signal.component_type.value} failure on "
                f"{signal.component_id}: {signal.message}"
            ),
        )


class DatabaseAlertingStrategy(AlertingStrategy):
    alert_type = "P0_DATABASE_PAGE"
    priority = "P0"
    routing_key = "database-oncall"


class MCPHostAlertingStrategy(AlertingStrategy):
    alert_type = "P0_MCP_HOST_PAGE"
    priority = "P0"
    routing_key = "mcp-platform-oncall"


class APIAlertingStrategy(AlertingStrategy):
    alert_type = "P1_API_INCIDENT"
    priority = "P1"
    routing_key = "api-oncall"


class QueueAlertingStrategy(AlertingStrategy):
    alert_type = "P1_QUEUE_BACKLOG"
    priority = "P1"
    routing_key = "async-platform-oncall"


class CacheAlertingStrategy(AlertingStrategy):
    alert_type = "P2_CACHE_DEGRADATION"
    priority = "P2"
    routing_key = "cache-oncall"


class NoSQLAlertingStrategy(AlertingStrategy):
    alert_type = "P2_NOSQL_DEGRADATION"
    priority = "P2"
    routing_key = "storage-oncall"


STRATEGIES: dict[ComponentType, AlertingStrategy] = {
    ComponentType.RDBMS: DatabaseAlertingStrategy(),
    ComponentType.MCP_HOST: MCPHostAlertingStrategy(),
    ComponentType.API: APIAlertingStrategy(),
    ComponentType.ASYNC_QUEUE: QueueAlertingStrategy(),
    ComponentType.CACHE: CacheAlertingStrategy(),
    ComponentType.NOSQL: NoSQLAlertingStrategy(),
}


def get_alerting_strategy(component_type: ComponentType) -> AlertingStrategy:
    return STRATEGIES.get(component_type, AlertingStrategy())
