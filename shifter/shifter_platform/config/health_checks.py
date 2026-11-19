"""Additional portal health-check plugins.

The public ``/health`` endpoint is the ALB readiness surface. Keep new probes
inside the existing django-health-check registry so the endpoint preserves one
coarse response contract while reflecting the configured runtime dependencies.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from django.conf import settings
from health_check.backends import HealthCheck as HealthCheckPluginBase
from health_check.exceptions import ServiceUnavailable
from health_check.plugins import plugin_dir

__all__ = [
    "AuditLogDegradedHealthCheck",
    "ChannelLayerRedisHealthCheck",
    "channel_layer_uses_redis",
    "register_audit_log_degraded_health_check",
    "register_channel_layer_redis_health_check",
]

_logger = logging.getLogger(__name__)
_REDIS_CHANNEL_LAYER = "channels_redis.core.RedisChannelLayer"
_PROBE_TIMEOUT_SECONDS = 2.0


def channel_layer_uses_redis() -> bool:
    """Return whether the resolved default Channels backend is Redis."""
    channel_layers = getattr(settings, "CHANNEL_LAYERS", {})
    default_layer = channel_layers.get("default", {})
    return default_layer.get("BACKEND") == _REDIS_CHANNEL_LAYER


class ChannelLayerRedisHealthCheck(HealthCheckPluginBase):
    """Probe the configured Redis-backed Channels layer."""

    def check_status(self) -> None:
        try:
            self._probe()
        # readiness probe; Redis errors carry internal endpoints, so log the type only
        except Exception as exc:  # noqa: BLE001
            _logger.warning("channel-layer Redis readiness failed: exc_type=%s", type(exc).__name__)
            self.add_error(ServiceUnavailable("Channel layer Redis unavailable"))

    def _probe(self) -> bool:
        return _ping_configured_redis()


class AuditLogDegradedHealthCheck(HealthCheckPluginBase):
    """Report whether this worker has observed an audit write failure."""

    def check_status(self) -> None:
        from shared.audit import get_audit_health_snapshot

        snapshot = get_audit_health_snapshot()
        if snapshot.degraded:
            self.add_error(ServiceUnavailable("Audit logging degraded"))


def register_audit_log_degraded_health_check() -> None:
    """Register process-local audit degradation with the public health surface."""
    if any(plugin is AuditLogDegradedHealthCheck for plugin, _options in plugin_dir._registry):
        return
    plugin_dir.register(AuditLogDegradedHealthCheck)


def register_channel_layer_redis_health_check() -> None:
    """Register Redis readiness only when the default channel layer is Redis."""
    if not channel_layer_uses_redis():
        return
    if any(plugin is ChannelLayerRedisHealthCheck for plugin, _options in plugin_dir._registry):
        return
    plugin_dir.register(ChannelLayerRedisHealthCheck)


_redis_client_lock = threading.Lock()
_redis_client: Any = None


def _configured_redis_client() -> Any:
    """Return one process-wide client for the first configured channel-layer host.

    The probe uses its own connection pool. It must not send and receive through
    the shared channel layer. A concurrent WebSocket receive() on that layer makes
    channels_redis raise "Two event loops are trying to receive() on one channel
    layer at once!", so the probe failed while Redis was healthy.
    """
    global _redis_client
    with _redis_client_lock:
        if _redis_client is None:
            import redis

            host = settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]
            if isinstance(host, dict):
                options = {key: value for key, value in host.items() if key != "address"}
                address = host["address"]
            else:
                options, address = {}, host
            _redis_client = redis.Redis.from_url(
                address,
                socket_timeout=_PROBE_TIMEOUT_SECONDS,
                socket_connect_timeout=_PROBE_TIMEOUT_SECONDS,
                **options,
            )
        return _redis_client


def _ping_configured_redis() -> bool:
    """Send PING to the channel-layer Redis on the probe's own connection."""
    if not _configured_redis_client().ping():
        raise ServiceUnavailable("Channel layer Redis did not answer PING")
    return True
