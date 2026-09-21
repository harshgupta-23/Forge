output "alb_dns_name" {
  description = "Public DNS hostname of the Application Load Balancer."
  value       = aws_lb.forge_alb.dns_name
}

output "api_endpoint_url" {
  description = "HTTP REST root endpoint for Forge."
  value       = "http://${aws_lb.forge_alb.dns_name}"
}

output "websocket_url" {
  description = "WebSocket entrypoint URL for desktop UI connection."
  value       = "ws://${aws_lb.forge_alb.dns_name}"
}

output "rds_endpoint" {
  description = "Database connection endpoint for PostgreSQL."
  value       = aws_db_instance.forge_postgres.endpoint
}

output "ecs_cluster_name" {
  description = "ECS Fargate cluster identifier."
  value       = aws_ecs_cluster.forge_cluster.name
}

output "ecs_service_name" {
  description = "ECS Fargate running service identifier."
  value       = aws_ecs_service.forge_service.name
}

