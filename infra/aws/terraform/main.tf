# HomeAI Cloud — Tier 2 root module (docs/08 A-1 … A-8).
#
# Split across:
#   versions.tf / providers.tf / variables.tf / outputs.tf / data.tf
#   security_groups.tf / acm.tf / alb.tf / iam.tf / ecr.tf
#   github_oidc.tf / asg.tf / cloudwatch.tf
#   templates/user_data_{api,worker}.sh.tpl
#
# Intentionally NOT managed here (reuse Nov demo / provision.sh):
#   - RDS PostgreSQL instance and its master secret
#   - S3 media bucket + lifecycle
#   - Secrets Manager secrets under homeai/*
#   - Single-EC2 instance, Elastic IP, homeai-ec2-role (legacy fallback)
#   - MongoDB Atlas (A-2 — create outside Terraform; put URLs into Secrets Manager)
#
# See README.md for init / plan / apply / destroy and cost controls.
