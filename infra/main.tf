# Panther — infrastruttura AWS (free tier)
#
# S3 privato + CloudFront con Origin Access Control + ruolo OIDC per GitHub
# Actions. Nessuna chiave statica: il deploy assume il ruolo via token OIDC.
#
#   terraform init && terraform apply -var 'github_repo=pdonorio/phanter'

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "eu-south-1" # Milano
}

variable "project" {
  type    = string
  default = "panther"
}

variable "github_repo" {
  type        = string
  description = "owner/repo autorizzato ad assumere il ruolo di deploy"
  default     = "pdonorio/phanter"
}

locals {
  bucket_name = "${var.project}-static-${data.aws_caller_identity.current.account_id}"
}

data "aws_caller_identity" "current" {}

# ----------------------------------------------------------------- S3 (privato)
resource "aws_s3_bucket" "static" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "static" {
  bucket                  = aws_s3_bucket.static.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "static" {
  bucket = aws_s3_bucket.static.id
  versioning_configuration {
    # Il DB è rigenerato ogni notte: il versioning permette il rollback a una
    # build precedente se un cambio a monte rompe il parsing.
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "static" {
  bucket = aws_s3_bucket.static.id
  rule {
    id     = "scadenza-versioni-vecchie"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30 # oltre non serve, e il free tier S3 è 5GB
    }
  }
}

# ------------------------------------------------------------------- CloudFront
resource "aws_cloudfront_origin_access_control" "static" {
  name                              = "${var.project}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "cdn" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # EU/NA: sufficiente e più economico
  comment             = "${var.project} PWA"

  origin {
    domain_name              = aws_s3_bucket.static.bucket_regional_domain_name
    origin_id                = "s3-${local.bucket_name}"
    origin_access_control_id = aws_cloudfront_origin_access_control.static.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-${local.bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true # gzip/brotli: il .db comprime molto bene
    # Managed-CachingOptimized: rispetta gli header Cache-Control impostati
    # dai workflow in fase di upload.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # SPA: le rotte lato client devono ricadere su index.html.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Solo CloudFront può leggere il bucket.
data "aws_iam_policy_document" "bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.static.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.cdn.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "static" {
  bucket = aws_s3_bucket.static.id
  policy = data.aws_iam_policy_document.bucket.json
}

# ------------------------------------------------------- OIDC per GitHub Actions
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Vincolo al repo: senza questo, qualunque repo GitHub potrebbe assumere
    # il ruolo. Ristretto anche al branch main.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repo}:ref:refs/heads/main",
        "repo:${var.github_repo}:environment:production",
      ]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.project}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.static.arn]
  }
  statement {
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.static.arn}/*"]
  }
  statement {
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.cdn.arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# ---------------------------------------------------------------------- output
# Da riportare nelle Variables del repo GitHub.
output "aws_deploy_role_arn" { value = aws_iam_role.deploy.arn }
output "s3_bucket" { value = aws_s3_bucket.static.id }
output "cloudfront_distribution_id" { value = aws_cloudfront_distribution.cdn.id }
output "panther_domain" { value = aws_cloudfront_distribution.cdn.domain_name }
