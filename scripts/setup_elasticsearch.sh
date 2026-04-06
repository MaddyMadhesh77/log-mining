#!/bin/bash
# Setup script for Elasticsearch

echo "Setting up Elasticsearch..."

# Download Elasticsearch if not present
if [ ! -d "elasticsearch-8.0.0" ]; then
    wget https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-8.0.0-linux-x86_64.tar.gz
    tar -xzf elasticsearch-8.0.0-linux-x86_64.tar.gz
fi

# Start Elasticsearch
echo "Starting Elasticsearch..."
./elasticsearch-8.0.0/bin/elasticsearch &

echo "Elasticsearch setup complete"
