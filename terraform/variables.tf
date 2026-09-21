variable "aws_region" {
  description = "AWS region for provisioning Forge cloud infrastructure."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Base identifier for Forge cloud resources."
  type        = string
  default     = "forge-agent"
}

variable "environment" {
  description = "Deployment environment tier (e.g. production, staging, dev)."
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "CIDR block for the dedicated Forge VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "forge"
}

variable "db_username" {
  description = "Master administrative username for RDS PostgreSQL."
  type        = string
  default     = "forge_admin"
}

variable "db_password" {
  description = "Master administrative password for RDS PostgreSQL."
  type        = string
  sensitive   = true
  default     = "ForgeMasterPassword123!"
}

variable "db_instance_class" {
  description = "RDS DB instance compute shape."
  type        = string
  default     = "db.t4g.micro"
}

variable "container_image" {
  description = "URI of the container image published to ECR/DockerHub."
  type        = string
  default     = "forge-backend:latest"
}

variable "container_cpu" {
  description = "CPU units allocated to ECS Fargate task (1024 = 1 vCPU)."
  type        = number
  default     = 1024
}

variable "container_memory" {
  description = "Memory allocated to ECS Fargate task (2048 = 2 GB)."
  type        = number
  default     = 2048
}

variable "backend_port" {
  description = "Container and service listening port for FastAPI / WebSockets."
  type        = number
  default     = 8765
}

variable "alb_idle_timeout" {
  description = "Extended ALB idle timeout in seconds to prevent WebSocket disconnects during long agent reasoning chains."
  type        = number
  default     = 300
}

