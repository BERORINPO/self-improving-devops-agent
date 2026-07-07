# AutoSRE infrastructure - Terraform entry point.
#
# This configuration mirrors the live, hand-verified deployment in project
# "bero-devops-agent" (region asia-northeast1). See README.md for the honest
# framing: the demo was deployed by hand first, this code reproduces it.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
