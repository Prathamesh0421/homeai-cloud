# ---------------------------------------------------------------------------
# EC2 instance role for API + worker ASGs (extends Nov ec2-policy.json with ECR pull)
# Separate from homeai-ec2-role so Terraform does not own/destroy the demo instance.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${local.name_prefix}-instance-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid = "S3BucketAccess"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:ListBucketMultipartUploads",
      "s3:ListMultipartUploadParts",
      "s3:AbortMultipartUpload",
    ]
    resources = [
      "arn:aws:s3:::${local.s3_bucket}",
      "arn:aws:s3:::${local.s3_bucket}/*",
    ]
  }

  statement {
    sid = "SNSTopics"
    actions = [
      "sns:CreateTopic",
      "sns:Publish",
      "sns:Subscribe",
      "sns:Unsubscribe",
      "sns:ListSubscriptionsByTopic",
      "sns:GetSubscriptionAttributes",
      "sns:SetSubscriptionAttributes",
    ]
    resources = ["arn:aws:sns:${var.aws_region}:${local.account_id}:homeai-*"]
  }

  statement {
    sid       = "SNSListTopics"
    actions   = ["sns:ListTopics"]
    resources = ["*"]
  }

  statement {
    sid = "SecretsManager"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:${var.secrets_prefix}/*",
    ]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/homeai/*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/homeai/*:*",
    ]
  }

  statement {
    sid = "CloudWatchAgent"
    actions = [
      "cloudwatch:PutMetricData",
      "ec2:DescribeVolumes",
      "ec2:DescribeTags",
    ]
    resources = ["*"]
  }

  # ECR pull (A-3 / A-4) — instances never push.
  statement {
    sid = "ECRAuth"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ECRPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:DescribeRepositories",
      "ecr:DescribeImages",
    ]
    resources = [
      for name in local.ecr_repos :
      "arn:aws:ecr:${var.aws_region}:${local.account_id}:repository/${var.project_name}/${name}"
    ]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "${local.name_prefix}-instance"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name_prefix}-instance-profile"
  role = aws_iam_role.instance.name
  tags = local.common_tags
}
