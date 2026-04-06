# Setup Guide

## Prerequisites

- Python 3.10+
- Java 11+
- Docker and Docker Compose (for containerized deployment)
- 4GB RAM minimum
- Git

## Installation Steps

### 1. Clone Repository

```bash
git clone <repository-url>
cd Large-Scale-Software-Log-Pattern-Mining
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# On Windows
venv\Scripts\activate

# On Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

Copy `.env` file and update settings:

```bash
cp .env .env.local
# Edit .env.local with your settings
```

### 5. Start Services

#### Option A: Using Docker Compose (Recommended)

```bash
docker-compose up -d
```

Wait for services to be ready:
```bash
docker-compose ps
```

#### Option B: Manual Setup

1. Start Kafka:
```bash
bash scripts/setup_kafka.sh
```

2. Start Elasticsearch:
```bash
bash scripts/setup_elasticsearch.sh
```

3. Start MongoDB:
```bash
docker run -d -p 27017:27017 mongo:5.0
```

### 6. Verify Installation

```bash
# Test imports
python -c "import pyspark; import tensorflow; print('OK')"

# Run tests
python -m pytest tests/ -v
```

## Training ML Models

1. Open Jupyter:
```bash
jupyter notebook
```

2. Go to `notebooks/05_model_training.ipynb`

3. Train and save model to `models/anomaly_detector.h5`

## Running the Pipeline

### Generate Sample Data
```bash
python -c "
from src.ingestion.log_generator import LogGenerator
from src.ingestion.file_ingestion import FileIngestion

gen = LogGenerator()
logs = gen.generate_batch(10000)
FileIngestion.write_logs_to_file(logs, 'data/raw_logs/sample.json')
"
```

### Run Pattern Mining
```bash
python notebooks/03_pattern_mining.ipynb
```

### Run Anomaly Detection
```bash
python notebooks/04_anomaly_detection.ipynb
```

## Monitoring

### Jupyter Notebooks
- Access at: http://localhost:8888

### Kibana
- Access at: http://localhost:5601

### Application Dashboard
- Access at: http://localhost:5000

## Troubleshooting

### Kafka Connection Issues
- Ensure `KAFKA_BROKERS` in `.env` points to correct broker
- Check Kafka is running: `docker-compose ps`

### Out of Memory Errors
- Increase `spark.driver.memory` in `config/spark_config.py`
- Process data in smaller batches

### Model Not Found
- Place .h5 file in `models/` directory
- Update path in `config/constants.py`

## Stopping Services

```bash
# Stop Docker services
docker-compose down

# Or manually stop services
bash scripts/stop_pipeline.sh
```

## Advanced Configuration

### Changing Batch Size
Edit `config/constants.py`:
```python
BATCH_SIZE = 2000  # Increase from 1000
```

### Adding New Log Source
1. Create handler in `src/ingestion/`
2. Update factory in `src/ingestion/__init__.py`
3. Configure in `config/`

### Custom Pattern Mining Rules
Edit `src/mining/frequent_pattern.py` and `association_rules.py`
