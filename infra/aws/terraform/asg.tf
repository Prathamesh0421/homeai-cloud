# ---------------------------------------------------------------------------
# Launch templates + Auto Scaling groups (A-4, A-7)
# ---------------------------------------------------------------------------

locals {
  user_data_common = {
    aws_region     = var.aws_region
    account_id     = local.account_id
    project_name   = var.project_name
    ecr_image_tag  = var.ecr_image_tag
    s3_bucket      = local.s3_bucket
    rds_endpoint   = var.rds_endpoint
    secrets_prefix = var.secrets_prefix
    domain_name    = var.domain_name
    team           = var.team
    repo_clone_url = var.repo_clone_url
    repo_ref       = var.repo_ref
    environment    = var.environment
    log_group_base = "/homeai/${var.environment}"
  }
}

resource "aws_launch_template" "api" {
  count = var.enable_asg ? 1 : 0

  name_prefix   = "${local.name_prefix}-api-"
  image_id      = data.aws_ami.ubuntu_2204.id
  instance_type = var.api_instance_type
  key_name      = var.key_name != "" ? var.key_name : null

  iam_instance_profile {
    name = aws_iam_instance_profile.instance.name
  }

  vpc_security_group_ids = [aws_security_group.instances.id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data_api.sh.tpl", local.user_data_common))

  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, {
      Name = "${local.name_prefix}-api"
      Role = "api"
    })
  }

  tags = merge(local.common_tags, { Role = "api" })
}

resource "aws_launch_template" "worker" {
  count = var.enable_asg ? 1 : 0

  name_prefix   = "${local.name_prefix}-worker-"
  image_id      = data.aws_ami.ubuntu_2204.id
  instance_type = var.worker_instance_type
  key_name      = var.key_name != "" ? var.key_name : null

  iam_instance_profile {
    name = aws_iam_instance_profile.instance.name
  }

  vpc_security_group_ids = [aws_security_group.instances.id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data_worker.sh.tpl", local.user_data_common))

  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size           = 40
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, {
      Name = "${local.name_prefix}-worker"
      Role = "worker"
    })
  }

  tags = merge(local.common_tags, { Role = "worker" })
}

resource "aws_autoscaling_group" "api" {
  count = var.enable_asg ? 1 : 0

  name                      = "${local.name_prefix}-api"
  min_size                  = var.api_asg_min
  max_size                  = var.api_asg_max
  desired_capacity          = var.api_asg_desired
  vpc_zone_identifier       = local.public_subnet_ids
  health_check_type         = "ELB"
  health_check_grace_period = 300
  target_group_arns         = [aws_lb_target_group.api.arn]

  launch_template {
    id      = aws_launch_template.api[0].id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-api"
    propagate_at_launch = true
  }

  tag {
    key                 = "Role"
    value               = "api"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "worker" {
  count = var.enable_asg ? 1 : 0

  name                = "${local.name_prefix}-worker"
  min_size            = var.worker_asg_min
  max_size            = var.worker_asg_max
  desired_capacity    = var.worker_asg_desired
  vpc_zone_identifier = local.public_subnet_ids
  # Workers are not behind the ALB; EC2 health only.
  health_check_type         = "EC2"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.worker[0].id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-worker"
    propagate_at_launch = true
  }

  tag {
    key                 = "Role"
    value               = "worker"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Target tracking — CPU 60% (A-7). Worker backlog custom metric (S-7) can replace
# this later; keep CPU as the fallback so scale works before C3 publishes backlog.
resource "aws_autoscaling_policy" "api_cpu" {
  count = var.enable_asg ? 1 : 0

  name                   = "${local.name_prefix}-api-cpu-60"
  autoscaling_group_name = aws_autoscaling_group.api[0].name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = var.cpu_target_percent
  }
}

resource "aws_autoscaling_policy" "worker_cpu" {
  count = var.enable_asg ? 1 : 0

  name                   = "${local.name_prefix}-worker-cpu-60"
  autoscaling_group_name = aws_autoscaling_group.worker[0].name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = var.cpu_target_percent
  }
}
