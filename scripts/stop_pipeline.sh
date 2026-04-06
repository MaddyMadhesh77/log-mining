#!/bin/bash
# Stop the pipeline

echo "Stopping log pattern mining pipeline..."

# Stop Docker containers
docker-compose down

echo "Pipeline stopped"
