# ---------------------------------------------------------------------------
# Security groups (A-5)
#   ALB: 80/443 from the world
#   Instances: 80 from ALB SG only; 22 from team_ssh_cidrs
#   RDS: reuse existing SG — add 5432 from instance SG when rds_security_group_id is set
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "HomeAI ALB - HTTP/HTTPS from internet"
  vpc_id      = local.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-alb" })
}

resource "aws_security_group" "instances" {
  name        = "${local.name_prefix}-instances"
  description = "HomeAI ASG instances - app port from ALB, SSH from team"
  vpc_id      = local.vpc_id

  # Port 80: Caddy (SITE_ADDRESS=:80); TLS terminates at the ALB.
  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-instances" })
}

resource "aws_security_group_rule" "instances_ssh" {
  for_each = toset(var.team_ssh_cidrs)

  type              = "ingress"
  security_group_id = aws_security_group.instances.id
  description       = "SSH from team CIDR ${each.value}"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [each.value]
}

# Do not recreate the Nov-demo RDS SG. Only open 5432 from the new instance SG.
resource "aws_security_group_rule" "rds_from_instances" {
  count = var.rds_security_group_id != "" ? 1 : 0

  type                     = "ingress"
  security_group_id        = var.rds_security_group_id
  description              = "PostgreSQL from HomeAI Tier-2 ASG instances"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.instances.id
}
