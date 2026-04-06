#!/bin/bash
# Setup script for Hadoop

echo "Setting up Hadoop..."

# Download Hadoop if not present
if [ ! -d "hadoop-3.3.0" ]; then
    wget https://archive.apache.org/dist/hadoop/common/hadoop-3.3.0/hadoop-3.3.0.tar.gz
    tar -xzf hadoop-3.3.0.tar.gz
fi

export JAVA_HOME=/usr/lib/jvm/java-11-openjdk
export HADOOP_HOME=$PWD/hadoop-3.3.0

# Format namenode
$HADOOP_HOME/bin/hdfs namenode -format

# Start HDFS
echo "Starting HDFS..."
$HADOOP_HOME/sbin/start-dfs.sh

echo "Hadoop setup complete"
