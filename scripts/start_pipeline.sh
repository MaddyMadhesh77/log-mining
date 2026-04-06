#!/bin/bash
# Start the pipeline

echo "Starting log pattern mining pipeline..."

# Start services via Docker Compose
docker-compose up -d

# Wait for services to be ready
sleep 10

# Run the main pipeline
python -m src.processing.pipeline

echo "Pipeline started"
