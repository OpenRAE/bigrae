"""Tests for the portal ``/health`` readiness endpoint (#477).

Per ``docs/_deprecated/architecture/portal-health-readiness-preflight-477.md`` the public
``/health`` surface must reflect the real ``django-health-check`` DB / cache /
storage probes. The ``HealthCheckMiddleware`` may normalize the Host header so
ALB / ingress-IP probes admit, but it must not create the response. The
public body must stay coarse so a real dependency failure does not leak DSNs,
bucket names, secret IDs, or private hostnames.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client
from health_check.exceptions import ServiceUnavailable
from health_check.plugins import plugin_dir

# A non-secret sentinel used as the forced failure reason in probe-patches.
# Tests use it as a positive control: if the public response surfaces *this*
# string, the response is rendering the probe's raw error text (and would
# also surface real DSNs / hostnames in production).
_FORCED_FAILURE_REASON = "shifter-477-forced-probe-failure"

# Substrings that must never appear in the public ``/health`` body. The list
# tracks the Anti-Patterns block of the #477 preflight.
_FORBIDDEN_LEAK_MARKERS = (
    "postgres://",
    "postgresql://",
    "rediss://",
    "redis://",
    "traceback",
    "stack trace",
    "secret_id=",
    "secret_arn=",
    "aws_secret_",
    "s3://",
    "gs://",
    "arn:aws:secretsmanager",
    ".rds.amazonaws.com",
    ".cache.amazonaws.com",
    ".internal:",
    # Per-probe raw error strings must be replaced with a coarse token before
    # they reach the public body.
    _FORCED_FAILURE_REASON,
)


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_audit_health_state():
    from shared.audit import reset_audit_health

    reset_audit_health()
    yield
    reset_audit_health()


def _get_health(path: str = "/health/", **extra) -> tuple[int, str]:
    """Return (status_code, decoded body) for a GET against ``path``.

    Tests intentionally do not follow redirects: ALB does not follow them
    either, so a 301 here is a regression in the no-trailing-slash path.
    """
    response = Client().get(path, **extra)
    body = response.content.decode("utf-8", errors="replace")
    return response.status_code, body


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_health_returns_200_when_probes_pass():
    status, _ = _get_health("/health/")
    assert status == 200


def test_health_runs_the_real_django_health_check_view():
    """The old middleware short-circuited ``/health`` and returned ``b"OK"``.
    The new behavior must run the real ``django-health-check`` view, so the
    body must contain probe labels rather than the synthetic ``OK`` token.
    """
    status, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    assert status == 200
    # The installed probes are db, cache, storage. At least the DB backend
    # label must appear in the response payload.
    assert "DatabaseBackend" in body, f"expected django-health-check probe labels in /health/ body, got: {body!r}"
    # The hard-coded short-circuit body is exactly b"OK"; ensure we are NOT
    # serving that.
    assert body.strip() != "OK"


def test_health_no_trailing_slash_resolves_without_redirect():
    """ALB tfvars currently set ``health_check_path = "/health"`` (no
    trailing slash). ALB does not follow 301 redirects, so the no-slash
    route must resolve directly to the same view.
    """
    response = Client().get("/health")  # follow=False (default)
    assert response.status_code == 200, (
        f"/health (no trailing slash) returned {response.status_code}; "
        "ALB does not follow 3xx so this must be a direct 200."
    )


# ---------------------------------------------------------------------------
# Dependency probe failure paths
# ---------------------------------------------------------------------------


def _force_probe_failure(target: str):
    return patch(target, side_effect=ServiceUnavailable(_FORCED_FAILURE_REASON))


@pytest.fixture
def health_check_registry():
    """Restore the global django-health-check plugin registry after tests."""
    original_registry = list(plugin_dir._registry)
    try:
        yield plugin_dir._registry
    finally:
        plugin_dir._registry = original_registry


def test_health_returns_non_200_when_db_probe_fails():
    with _force_probe_failure("health_check.db.backends.DatabaseBackend.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "DB probe failure must surface as a non-200 /health"


def test_health_returns_non_200_when_cache_probe_fails():
    with _force_probe_failure("health_check.cache.backends.CacheBackend.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "cache probe failure must surface as a non-200 /health"


def test_health_returns_non_200_when_storage_probe_fails():
    with _force_probe_failure("health_check.storage.backends.DefaultFileStorageHealthCheck.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "storage probe failure must surface as a non-200 /health"


def test_in_memory_channel_layer_does_not_register_redis_probe(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()

    assert all(plugin is not ChannelLayerRedisHealthCheck for plugin, _ in health_check_registry)


def test_redis_channel_layer_registers_redis_probe(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()

    assert any(plugin is ChannelLayerRedisHealthCheck for plugin, _ in health_check_registry)


def test_redis_channel_layer_registration_is_idempotent(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()
    register_channel_layer_redis_health_check()

    assert [plugin for plugin, _ in health_check_registry].count(ChannelLayerRedisHealthCheck) == 1


def test_redis_health_check_uses_installed_health_check_plugin_base():
    from health_check.backends import HealthCheck

    from config.health_checks import ChannelLayerRedisHealthCheck

    assert issubclass(ChannelLayerRedisHealthCheck, HealthCheck)


def test_audit_health_check_registers_idempotently(health_check_registry):
    from config.health_checks import AuditLogDegradedHealthCheck, register_audit_log_degraded_health_check

    health_check_registry.clear()

    register_audit_log_degraded_health_check()
    register_audit_log_degraded_health_check()

    assert [plugin for plugin, _ in health_check_registry].count(AuditLogDegradedHealthCheck) == 1


def test_health_surfaces_degraded_audit_health_coarsely(health_check_registry):
    from config.health_checks import register_audit_log_degraded_health_check
    from shared.audit import mark_audit_degraded

    health_check_registry.clear()
    register_audit_log_degraded_health_check()

    mark_audit_degraded(TypeError(_FORCED_FAILURE_REASON))

    status, body = _get_health("/health/", HTTP_ACCEPT="application/json")

    assert status != 200, "degraded audit health must be machine-visible on /health"
    assert "AuditLogDegradedHealthCheck" in body, f"expected audit-health probe label in body, got: {body!r}"
    assert '"unavailable"' in body, f"expected coarse 'unavailable' token in body, got: {body!r}"
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, f"public /health body leaked sensitive marker {marker!r}: {body!r}"


class _FakeRedis:
    """Stand-in for ``redis.Redis`` that records how the probe built and used it."""

    def __init__(self, ping_result: bool = True, ping_error: Exception | None = None):
        self.ping_result = ping_result
        self.ping_error = ping_error
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        if self.ping_error is not None:
            raise self.ping_error
        return self.ping_result


@pytest.fixture
def fake_redis(monkeypatch, settings):
    """Replace the ``redis.Redis.from_url`` seam and reset the cached probe client."""
    import redis

    import config.health_checks as health_checks

    settings.CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [
                    {
                        "address": "rediss://redis.invalid:6378/0",
                        "ssl_ca_data": "synthetic-ca",
                        "ssl_cert_reqs": "required",
                    }
                ]
            },
        }
    }
    client = _FakeRedis()
    calls: list[tuple[str, dict]] = []

    def from_url(url, **options):
        calls.append((url, options))
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    monkeypatch.setattr(health_checks, "_redis_client", None)
    yield client, calls
    monkeypatch.setattr(health_checks, "_redis_client", None)


def test_redis_health_check_passes_when_ping_succeeds(fake_redis):
    from config.health_checks import ChannelLayerRedisHealthCheck

    client, _ = fake_redis
    check = ChannelLayerRedisHealthCheck()
    check.check_status()

    assert check.errors == []
    assert client.pings == 1


def test_redis_health_check_reports_an_error_when_ping_fails(fake_redis):
    from config.health_checks import ChannelLayerRedisHealthCheck

    client, _ = fake_redis
    client.ping_error = ConnectionError("synthetic connection failure")
    check = ChannelLayerRedisHealthCheck()
    check.check_status()

    assert len(check.errors) == 1
    assert "redis.invalid" not in str(check.errors[0])


def test_redis_health_check_reports_an_error_when_ping_returns_false(fake_redis):
    from config.health_checks import ChannelLayerRedisHealthCheck

    client, _ = fake_redis
    client.ping_result = False
    check = ChannelLayerRedisHealthCheck()
    check.check_status()

    assert len(check.errors) == 1


def test_redis_probe_client_uses_the_configured_host_options_and_timeouts(fake_redis):
    from config.health_checks import _PROBE_TIMEOUT_SECONDS, _ping_configured_redis

    _, calls = fake_redis
    assert _ping_configured_redis() is True

    assert calls == [
        (
            "rediss://redis.invalid:6378/0",
            {
                "ssl_ca_data": "synthetic-ca",
                "ssl_cert_reqs": "required",
                "socket_timeout": _PROBE_TIMEOUT_SECONDS,
                "socket_connect_timeout": _PROBE_TIMEOUT_SECONDS,
            },
        )
    ]


def test_redis_probe_client_accepts_a_url_host(fake_redis, settings):
    from config.health_checks import _ping_configured_redis

    _, calls = fake_redis
    settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"] = ["redis://redis.invalid:6379/0"]

    assert _ping_configured_redis() is True
    assert calls[0][0] == "redis://redis.invalid:6379/0"
    assert set(calls[0][1]) == {"socket_timeout", "socket_connect_timeout"}


@pytest.mark.usefixtures("fake_redis")
def test_redis_probe_client_accepts_a_plain_host_and_port(settings, monkeypatch):
    """The non-TLS channel layer emits a ``(host, port)`` pair (``config._channels``)."""
    import redis

    from config.health_checks import _PROBE_TIMEOUT_SECONDS, _ping_configured_redis

    built: list[dict] = []

    def fake_init(self, **options):
        built.append(options)

    monkeypatch.setattr(redis.Redis, "__init__", fake_init)
    monkeypatch.setattr(redis.Redis, "ping", lambda self: True)
    settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"] = [("redis", 6379)]

    assert _ping_configured_redis() is True
    assert built == [
        {
            "host": "redis",
            "port": 6379,
            "db": 0,
            "socket_timeout": _PROBE_TIMEOUT_SECONDS,
            "socket_connect_timeout": _PROBE_TIMEOUT_SECONDS,
        }
    ]


def test_concurrent_redis_probes_all_pass_and_share_one_client(fake_redis):
    """Concurrent health checks must not refuse each other (the old shared-layer defect)."""
    from concurrent.futures import ThreadPoolExecutor

    from config.health_checks import _ping_configured_redis

    client, calls = fake_redis
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: _ping_configured_redis(), range(160)))

    assert results == [True] * 160
    assert client.pings == 160
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Host-header admission (ALB / ingress-IP) reaches the real view
# ---------------------------------------------------------------------------


def test_health_with_alb_host_header_reaches_real_view():
    """ALB / GCP ingress probes arrive with the load balancer's internal IP
    as the ``Host`` header. The IP is intentionally NOT in
    ``DJANGO_ALLOWED_HOSTS`` (see
    ``scripts/gcp/render_runtime_env.py:101-107``). The middleware must
    normalize the Host so the real django-health-check view runs — without
    raising ``DisallowedHost`` AND without returning a synthetic ``OK``.
    """
    status, body = _get_health(
        "/health/",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )
    assert status == 200
    assert "DatabaseBackend" in body, "ALB-IP Host probe must reach the real view (probe labels in body)"


def test_health_with_alb_host_header_no_trailing_slash():
    """Combination of the two regression vectors: ALB tfvars probe (no
    trailing slash, internal-IP Host)."""
    status, body = _get_health(
        "/health",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )
    assert status == 200, body
    # Positive structural assertion: the ALB+no-slash path must reach the real
    # django-health-check view, not a synthetic short-circuit. A regression to
    # JsonResponse({"status": "ok"}) would still 200 but would drop the probe
    # labels — guard against that here.
    assert "DatabaseBackend" in body, (
        f"ALB-IP + no-trailing-slash probe must reach the real view (probe labels expected in body), got: {body!r}"
    )


def test_health_is_not_redirected_when_ssl_redirect_enabled(settings):
    """Production enables ``SECURE_SSL_REDIRECT``. ALB health checks are plain
    HTTP and do not send ``X-Forwarded-Proto: https``, so `/health` must be
    exempt from HTTPS redirects and still run the real readiness probes.
    """
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_REDIRECT_EXEMPT = [r"^health/?$"]

    status, body = _get_health(
        "/health",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )

    assert status == 200, body
    assert "DatabaseBackend" in body


# ---------------------------------------------------------------------------
# Coarse public body — no DSN / hostname / secret-ID / stack-trace leaks
# ---------------------------------------------------------------------------


def test_health_failure_body_is_coarse_on_db_failure():
    with _force_probe_failure("health_check.db.backends.DatabaseBackend.check_status"):
        _, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    # Positive structural assertion: the body must still expose the probe
    # label paired with the coarse "unavailable" token. Without this, a
    # regression to JsonResponse({"status": "unhealthy"}) would pass the
    # forbidden-marker scan below (no DSNs in {"status": "unhealthy"}) yet
    # silently drop the per-probe surface the #477 preflight requires.
    assert '"DatabaseBackend"' in body, f"expected DatabaseBackend probe label in coarse body, got: {body!r}"
    assert '"unavailable"' in body, f"expected coarse 'unavailable' token in body, got: {body!r}"
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, f"public /health body leaked sensitive marker {marker!r}: {body!r}"


def test_health_failure_body_is_coarse_on_cache_failure():
    with _force_probe_failure("health_check.cache.backends.CacheBackend.check_status"):
        _, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    # Positive structural assertion: the cache-failure body must still carry
    # the cache probe label and the coarse "unavailable" token. The label
    # rendered by django-health-check for the legacy CacheBackend plugin is
    # ``Cache(alias='default')``. See the db-failure test's note on why a
    # forbidden-marker-only scan is not sufficient.
    assert "Cache(alias=" in body, f"expected cache probe label in coarse body, got: {body!r}"
    assert '"unavailable"' in body, f"expected coarse 'unavailable' token in body, got: {body!r}"
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, body
