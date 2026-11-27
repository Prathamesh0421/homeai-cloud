# ---------------------------------------------------------------------------
# Account / AMI / network discovery
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_vpc" "selected" {
  id      = var.vpc_id != "" ? var.vpc_id : null
  default = var.vpc_id == "" ? true : null
}

# When subnet IDs are not passed, pick two default-VPC subnets in distinct AZs.
data "aws_subnets" "default_public" {
  count = length(var.public_subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_subnet" "picked" {
  for_each = toset(
    length(var.public_subnet_ids) > 0
    ? var.public_subnet_ids
    : slice(data.aws_subnets.default_public[0].ids, 0, min(2, length(data.aws_subnets.default_public[0].ids)))
  )
  id = each.value
}

# Canonical Ubuntu 22.04 (Jammy) amd64 — same family as provision.sh.
data "aws_ami" "ubuntu_2204" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  vpc_id     = data.aws_vpc.selected.id

  public_subnet_ids = (
    length(var.public_subnet_ids) > 0
    ? var.public_subnet_ids
    : [for s in data.aws_subnet.picked : s.id]
  )

  s3_bucket = var.s3_bucket_name != "" ? var.s3_bucket_name : "${var.project_name}-${var.team}-${local.account_id}"

  name_prefix = "${var.project_name}-${var.environment}"

  ecr_repos = toset([
    "c1-iot",
    "c2-alerts",
    "c3-data",
    "c3-worker",
    "c4-dashboard",
    "web", # Caddy image that embeds the SPA (infra/caddy/Dockerfile)
  ])

  common_tags = {
    Project     = "homeai-cloud"
    Environment = var.environment
  }
}
