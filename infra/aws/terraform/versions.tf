# HomeAI Cloud — Tier 2 AWS layout (docs/08_FINAL_DELIVERABLES.md A-1).
# Terraform + AWS provider versions. Local state only (*.tfstate* is gitignored).

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local backend by default. Switch to S3 + DynamoDB only if the team agrees;
  # do not commit state files.
}
