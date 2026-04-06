# System Architecture

## Overview

The Large-Scale Log Pattern Mining system is designed as a multi-layer architecture for processing, analyzing, and mining patterns from large volumes of system logs.

## Architecture Layers

### Layer 1: Data Sources
- System logs
- Application logs
- Custom log sources

### Layer 2: Data Ingestion
- Kafka for real-time streaming
- File-based batch ingestion
- Logstash/Fluentd integration

**Components:**
- `kafka_producer.py` - Produces log messages to Kafka
- `kafka_consumer.py` - Consumes logs from Kafka
- `file_ingestion.py` - Handles file-based log input
- `log_generator.py` - Generates synthetic logs for testing

### Layer 3: Data Processing
- Log Parsing (extracting structured data)
- Preprocessing (cleaning, normalization)
- Feature extraction

**Components:**
- `parsing/` - Log parsing algorithms (Drain, Regex)
- `preprocessing/` - Cleaning, tokenization, encoding
- `processing/` - Distributed processing (Spark)

### Layer 4: Analytics & Mining
- Pattern Mining (frequent, sequential)
- Anomaly Detection
- Clustering

**Components:**
- `mining/` - Pattern mining algorithms
- `anomaly_detection/` - Multiple detection methods
- `processing/spark_batch.py` - Batch processing
- `processing/spark_streaming.py` - Stream processing

### Layer 5: Storage
- HDFS for distributed storage
- Elasticsearch for indexing
- MongoDB for document storage

**Components:**
- `hdfs_handler.py` - HDFS operations
- `elasticsearch_handler.py` - ES indexing
- `nosql_handler.py` - MongoDB operations
- `storage_manager.py` - Unified interface

### Layer 6: Visualization
- Dashboards (Flask/Streamlit)
- Kibana integration
- Grafana integration
- Charts and alerts

**Components:**
- `dashboard.py` - Web dashboard
- `kibana_integration.py` - Kibana setup
- `grafana_integration.py` - Grafana setup
- `alert_manager.py` - Alert system

## Data Flow

```
Logs → Ingestion → Parsing → Preprocessing → Processing → Mining → Storage → Visualization
```

## Configuration

All configuration is centralized in `config/`:
- `constants.py` - All constants and paths
- `kafka_config.py` - Kafka settings
- `spark_config.py` - Spark settings
- `elasticsearch_config.py` - ES configuration
- `hdfs_config.py` - HDFS configuration

## Deployment Options

### Local Development
```bash
python -m src.processing.pipeline
```

### Docker Compose
```bash
docker-compose up -d
```

### Kubernetes (not included)
See deployment/k8s/ folder structure

## Performance Considerations

- **Batch Size**: Adjustable in `config/constants.py` (default: 1000)
- **Partitions**: Spark parallel partitions (default: 4)
- **Window Size**: For streaming operations (default: 50)
- **Min Support**: For pattern mining (default: 5%)
