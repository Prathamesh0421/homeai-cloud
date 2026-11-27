# ---------------------------------------------------------------------------
# Application Load Balancer (A-5, A-6)
# ---------------------------------------------------------------------------

resource "aws_lb" "api" {
  name               = "${local.name_prefix}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.public_subnet_ids

  # Idle timeout above default so long-poll / upload demos do not drop early.
  idle_timeout = 60

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-alb" })
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "instance"

  # D1 / docs/08: /api/v1/health/c4 every 15s; least outstanding requests; 30s drain.
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/api/v1/health/c4"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }

  # Terraform AWS provider: load_balancing_algorithm_type
  load_balancing_algorithm_type = "least_outstanding_requests"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-api-tg" })
}

# Always create HTTP :80. Redirect to HTTPS when the listener is enabled;
# otherwise forward so the stack is usable before DuckDNS ACM validation.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.enable_https_listener ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.enable_https_listener ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.api.arn
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.enable_https_listener ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = (
    var.enable_acm_validation_wait
    ? aws_acm_certificate_validation.site[0].certificate_arn
    : aws_acm_certificate.site.arn
  )

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
