# Portal Redis channel layer (ADR-018, ADR-044-R6, ADR-072).
#
# The portal stack owns the ElastiCache channel layer and publishes its posture
# to SSM Parameter Store. The EKS runtime env follows that posture, so portal,
# scheduler, and worker pods share one Django Channels layer. The AUTH token
# stays in Secrets Manager: the deploy tooling copies it into the EKS-owned
# redis secret container, and entrypoint.sh hydrates it from REDIS_SECRET_ID.

data "aws_ssm_parameter" "portal_channel_layer_backend" {
  name = "/shifter/${var.environment}/portal/channel-layer-backend"
}

locals {
  portal_redis_active = nonsensitive(data.aws_ssm_parameter.portal_channel_layer_backend.value) == "redis"
  redis_secret_arn    = lookup({ for name, secret in aws_secretsmanager_secret.platform : name => secret.arn }, "redis", "")
}

# The portal stack writes these only when Redis is the active backend, and an
# active backend requires the AUTH + in-transit encryption path. A missing
# parameter then fails the plan instead of silently using in-memory channels.
data "aws_ssm_parameter" "portal_redis_endpoint" {
  count = local.portal_redis_active ? 1 : 0
  name  = "/shifter/${var.environment}/portal/redis-endpoint"

  lifecycle {
    precondition {
      condition     = local.redis_secret_arn != ""
      error_message = "An active portal Redis channel layer requires the EKS-owned redis secret container (secret_names must include \"redis\")."
    }
  }
}

data "aws_ssm_parameter" "portal_redis_tls" {
  count = local.portal_redis_active ? 1 : 0
  name  = "/shifter/${var.environment}/portal/redis-tls"
}

data "aws_ssm_parameter" "portal_redis_ca_mode" {
  count = local.portal_redis_active ? 1 : 0
  name  = "/shifter/${var.environment}/portal/redis-ca-mode"
}

locals {
  channel_runtime_env = merge(
    { CHANNEL_LAYER_BACKEND = local.portal_redis_active ? "redis" : "in_memory" },
    local.portal_redis_active ? {
      REDIS_HOST      = nonsensitive(data.aws_ssm_parameter.portal_redis_endpoint[0].value)
      REDIS_PORT      = "6379"
      REDIS_TLS       = nonsensitive(data.aws_ssm_parameter.portal_redis_tls[0].value)
      REDIS_CA_MODE   = nonsensitive(data.aws_ssm_parameter.portal_redis_ca_mode[0].value)
      REDIS_SECRET_ID = local.redis_secret_arn
    } : {},
  )
}
