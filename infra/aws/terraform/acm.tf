# ---------------------------------------------------------------------------
# ACM certificate (A-6)
#
# DuckDNS has no Route 53 hosted zone in this account. After apply, add the
# ACM DNS validation CNAME/TXT that Terraform prints (see
# acm_validation_records output) in the DuckDNS control panel, then either:
#   terraform apply -var='enable_acm_validation_wait=true' -var='enable_https_listener=true'
# or validate in the ACM console and flip enable_https_listener.
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "site" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-cert" })
}

resource "aws_acm_certificate_validation" "site" {
  count = var.enable_acm_validation_wait ? 1 : 0

  certificate_arn = aws_acm_certificate.site.arn

  validation_record_fqdns = [
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.resource_record_name
  ]
}
