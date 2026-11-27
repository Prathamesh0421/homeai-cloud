# ---------------------------------------------------------------------------
# CloudWatch log groups + basic ALB alarms (A-8 stubs)
# Container log streams are created by the agent / awslogs driver under these groups.
# ---------------------------------------------------------------------------

locals {
  log_services = toset([
    "c1-iot",
    "c2-alerts",
    "c3-data",
    "c3-worker",
    "c4-dashboard",
    "caddy",
    "user-data",
  ])
}

resource "aws_cloudwatch_log_group" "services" {
  for_each = local.log_services

  name              = "/homeai/${var.environment}/${each.value}"
  retention_in_days = 14

  tags = merge(local.common_tags, { Service = each.value })
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB target 5xx > 5 in 2 minutes"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy" {
  alarm_name          = "${local.name_prefix}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB reports unhealthy targets"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  tags = local.common_tags
}

# Budget alarm itself stays in provision.sh ($25/month). Documented in README.
