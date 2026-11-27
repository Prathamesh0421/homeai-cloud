provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "homeai-cloud"
      Team      = var.team
      ManagedBy = "terraform"
      Tier      = "2"
    }
  }
}
