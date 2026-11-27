output "vpc_id" {
  description = "VPC used by the Tier-2 stack."
  value       = local.vpc_id
}

output "public_subnet_ids" {
  description = "Subnets used by the ALB and ASGs."
  value       = local.public_subnet_ids
}

output "alb_dns_name" {
  description = "ALB DNS name — point DuckDNS A/CNAME here (or use temporarily over HTTP)."
  value       = aws_lb.api.dns_name
}

output "alb_zone_id" {
  value = aws_lb.api.zone_id
}

output "alb_arn" {
  value = aws_lb.api.arn
}

output "api_target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "acm_certificate_arn" {
  value = aws_acm_certificate.site.arn
}

output "acm_validation_records" {
  description = "Add these DNS records in DuckDNS (or Route 53) to validate the ACM certificate."
  value = [
    for dvo in aws_acm_certificate.site.domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ]
}

output "instance_security_group_id" {
  value = aws_security_group.instances.id
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "instance_role_arn" {
  value = aws_iam_role.instance.arn
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.instance.name
}

output "ecr_repository_urls" {
  description = "Map of short name → repository URL for docker push/pull."
  value       = { for k, r in aws_ecr_repository.services : k => r.repository_url }
}

output "github_actions_ecr_role_arn" {
  description = "OIDC role ARN for the ECR push workflow (A-3). Set as AWS_ROLE_ARN / role-to-assume."
  value       = aws_iam_role.github_actions_ecr.arn
}

output "github_oidc_provider_arn" {
  value = local.github_oidc_provider_arn
}

output "api_asg_name" {
  value = try(aws_autoscaling_group.api[0].name, null)
}

output "worker_asg_name" {
  value = try(aws_autoscaling_group.worker[0].name, null)
}

output "s3_bucket_reused" {
  description = "Existing bucket name Terraform expects (not created here)."
  value       = local.s3_bucket
}

output "public_base_url_hint" {
  description = "Set PUBLIC_BASE_URL / DuckDNS once HTTPS is live."
  value       = "https://${var.domain_name}"
}

output "cloudwatch_log_groups" {
  value = [for g in aws_cloudwatch_log_group.services : g.name]
}
