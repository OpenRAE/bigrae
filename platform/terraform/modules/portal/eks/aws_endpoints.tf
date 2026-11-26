# ------------------------------------------------------------------------------
# Private AWS service endpoints for EKS management helpers (#2566)
# ------------------------------------------------------------------------------
# The OpenFGA rotation function calls Secrets Manager. The operator access node
# runs the Session Manager agent. These endpoints keep that traffic in the VPC,
# so the helpers need no internet egress. Private DNS makes every client in this
# VPC use the endpoints, so the endpoint group admits HTTPS from the VPC CIDR.
# ------------------------------------------------------------------------------

locals {
  interface_endpoint_services = toset([
    "ec2messages",
    "secretsmanager",
    "ssm",
    "ssmmessages",
  ])
}

resource "aws_security_group" "interface_endpoints" {
  name        = "${var.cluster_name}-aws-endpoints"
  description = "Private AWS service endpoints for the EKS VPC"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from EKS VPC clients"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-aws-endpoints"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoint_services

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for subnet in aws_subnet.private : subnet.id]
  security_group_ids  = [aws_security_group.interface_endpoints.id]
  private_dns_enabled = true

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-${each.key}-endpoint"
  })
}
