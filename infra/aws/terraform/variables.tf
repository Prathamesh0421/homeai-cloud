# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region (fixed for the course account)."
  type        = string
  default     = "us-west-2"
}

variable "team" {
  description = "Short team tag used in resource names and the existing S3 bucket."
  type        = string
  default     = "cmpe281"
}

variable "project_name" {
  description = "Prefix for new Tier-2 resources (does not rename Nov demo resources)."
  type        = string
  default     = "homeai"
}

variable "domain_name" {
  description = "Public hostname for ACM + PUBLIC_BASE_URL (DuckDNS or Route 53)."
  type        = string
  default     = "homeai.duckdns.org"
}

variable "environment" {
  description = "Environment label (tags, log group names)."
  type        = string
  default     = "prod"
}

# ---------------------------------------------------------------------------
# Network — default VPC + public subnets, or override with explicit IDs
# ---------------------------------------------------------------------------

variable "vpc_id" {
  description = "VPC ID. Empty = use the account default VPC."
  type        = string
  default     = ""
}

variable "public_subnet_ids" {
  description = "Two (or more) public subnet IDs for the ALB and ASGs. Empty = pick two default-VPC subnets in different AZs."
  type        = list(string)
  default     = []
}

variable "team_ssh_cidrs" {
  description = "CIDR blocks allowed to SSH to ASG instances (team IPs). Never 0.0.0.0/0 in a real apply."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Reused Nov-demo resources (provision.sh) — do NOT recreate or destroy
# ---------------------------------------------------------------------------

variable "s3_bucket_name" {
  description = "Existing media bucket from provision.sh (homeai-<team>-<accountid>). Empty = derive from account."
  type        = string
  default     = ""
}

variable "rds_security_group_id" {
  description = "Existing homeai-rds security group ID. When set, Terraform adds ingress 5432 from the ASG instance SG. Empty = skip (document manual rule)."
  type        = string
  default     = ""
}

variable "rds_endpoint" {
  description = "Existing RDS endpoint host (no port). Passed into user-data for .env render. Empty until apply-time."
  type        = string
  default     = ""
}

variable "secrets_prefix" {
  description = "Secrets Manager name prefix already created by provision.sh."
  type        = string
  default     = "homeai"
}

# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

variable "key_name" {
  description = "EC2 key pair for SSH (optional; leave empty to omit KeyName)."
  type        = string
  default     = ""
}

variable "api_instance_type" {
  description = "API ASG instance type (Caddy + C1/C2/C3-data/C4)."
  type        = string
  default     = "t3.medium"
}

variable "worker_instance_type" {
  description = "Worker ASG instance type (c3-worker / YAMNet)."
  type        = string
  default     = "t3.medium"
}

variable "api_asg_min" {
  type    = number
  default = 1
}

variable "api_asg_max" {
  type    = number
  default = 3
}

variable "api_asg_desired" {
  type    = number
  default = 1
}

variable "worker_asg_min" {
  type    = number
  default = 1
}

variable "worker_asg_max" {
  type    = number
  default = 2
}

variable "worker_asg_desired" {
  type    = number
  default = 1
}

variable "cpu_target_percent" {
  description = "Target tracking CPU utilization for both ASGs (A-7). Worker backlog metric is optional later."
  type        = number
  default     = 60
}

variable "ecr_image_tag" {
  description = "Image tag pulled by user-data (CI pushes :main or :sha)."
  type        = string
  default     = "main"
}

variable "repo_clone_url" {
  description = "Git clone URL used by user-data to fetch compose files (public repo)."
  type        = string
  default     = "https://github.com/Prathamesh0421/homeai-cloud.git"
}

variable "repo_ref" {
  description = "Git ref checked out on the instance for compose/Caddy files."
  type        = string
  default     = "main"
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC (A-3)
# ---------------------------------------------------------------------------

variable "github_org" {
  description = "GitHub org or user that owns the repo (OIDC trust)."
  type        = string
  default     = "Prathamesh0421"
}

variable "github_repo" {
  description = "Repository name for the ECR push role trust condition."
  type        = string
  default     = "homeai-cloud"
}

variable "create_github_oidc_provider" {
  description = "Create the account-level GitHub OIDC provider. Set false if one already exists."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Feature toggles (cost / partial apply)
# ---------------------------------------------------------------------------

variable "enable_acm_validation_wait" {
  description = "If true, aws_acm_certificate_validation waits on DNS records. DuckDNS TXT is manual — leave false until records exist."
  type        = bool
  default     = false
}

variable "enable_https_listener" {
  description = "Attach the 443 listener. Requires a validated ACM cert (or enable after DuckDNS TXT)."
  type        = bool
  default     = false
}

variable "enable_asg" {
  description = "Create launch templates + ASGs. Set false to plan networking/ECR/IAM first."
  type        = bool
  default     = true
}
