#!/bin/bash
# Setup script for Kafka

echo "Setting up Kafka..."

# Download Kafka if not present
if [ ! -d "kafka_2.13-3.0.0" ]; then
    wget https://archive.apache.org/dist/kafka/3.0.0/kafka_2.13-3.0.0.tgz
    tar -xzf kafka_2.13-3.0.0.tgz
fi

# Start Zookeeper
echo "Starting Zookeeper..."
./kafka_2.13-3.0.0/bin/zookeeper-server-start.sh ./kafka_2.13-3.0.0/config/zookeeper.properties &

# Wait for Zookeeper to start
sleep 5

# Start Kafka
echo "Starting Kafka..."
./kafka_2.13-3.0.0/bin/kafka-server-start.sh ./kafka_2.13-3.0.0/config/server.properties &

echo "Kafka setup complete"
