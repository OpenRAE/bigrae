# Mission Control

Reference for HTTP presentation and WebSocket interfaces.
Mission Control parses requests, calls owning services, and formats responses.
See [API development](../dev/api.md) for HTTP conventions.

## Responsibility

- HTTP endpoints and browser views.
- Terminal and status WebSocket transports.
- Current credential context and response formatting.

CMS and Engine retain lifecycle, resource custody, and access decisions.
The [lifecycle contracts](identity-lifecycle-contracts.md) explain continuing authorization.

## WebSocket Consumers

Routes come from `mission_control/routing.py`.
Browser connections pass the configured origin, session, and account checks.
Consumers retain current credential proof and recheck authority during the connection.
A cached user or an accepted socket is not continuing authority.

### SSHConsumer

**URL:** `ws/terminal/<instance_uuid>/`

The target segment is a native member key or supported instance UUID.
The consumer resolves it through `cms.services.connect_range_terminal`.
CMS authorizes the exact range and guest before Engine resolves SSH access.
Input and output pass through a bounded terminal transport.
Revocation, expiry, invalid proof, or unavailable authority closes the connection.

**Close codes:**

| Code | Meaning |
| --- | --- |
| `4001` | Not authenticated |
| `4003` | Permission denied |
| `4004` | Target not found |
| `4005` | Invalid request |
| `4500` | Server error |
| `4502` | SSH connection failed |
| `4503` | Service unavailable, including exhausted terminal capacity |

### RangeStatusConsumer

**URL:** `ws/range-status/<request_id>/`

The request UUID selects the exact range subscription.
The consumer authorizes through the owning service before joining its event group.
Each delivered event must match that subscription and current authority.
Redis notifications carry updates; PostgreSQL retains lifecycle truth.

`NGFWStatusConsumer` uses `ws/ngfw-status/<app_id>/` for device status.
It retains the same credential and owning-service boundaries.
See [unified credentials](access-credentials.md) for session revocation behavior.
