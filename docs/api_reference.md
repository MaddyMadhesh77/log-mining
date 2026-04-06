# API Reference

## Core Modules

### src.ingestion

#### LogGenerator
```python
from src.ingestion.log_generator import LogGenerator

gen = LogGenerator(seed=42)
log = gen.generate_log()  # Single log
logs = gen.generate_batch(100)  # Batch of 100 logs
```

#### KafkaProducer
```python
from src.ingestion.kafka_producer import KafkaProducer

producer = KafkaProducer(bootstrap_servers=['localhost:9092'])
producer.connect()
producer.send_log({'message': 'Test', ...})
producer.close()
```

#### FileIngestion
```python
from src.ingestion.file_ingestion import FileIngestion

logs = FileIngestion.read_logs_from_file('data/raw_logs/logs.json')
FileIngestion.write_logs_to_file(logs, 'data/parsed_logs/parsed.json')
```

### src.parsing

#### RegexParser
```python
from src.parsing.regex_parser import RegexParser

parser = RegexParser()
result = parser.parse("2024-01-01 ERROR: Connection failed")
# Returns: {'pattern': 'syslog', 'data': {...}}
```

#### LogNormalizer
```python
from src.parsing.log_normalizer import LogNormalizer

log = {'message': 'Test   error', 'level': 'error'}
normalized = LogNormalizer.normalize(log)
```

### src.preprocessing

#### LogCleaner
```python
from src.preprocessing.cleaner import LogCleaner

logs = [...]
cleaned = LogCleaner.remove_duplicates(logs)
cleaned = LogCleaner.remove_noise(cleaned)
```

#### Tokenizer
```python
from src.preprocessing.tokenizer import Tokenizer

tokens = Tokenizer.tokenize("Error occurred: timeout")
# Returns: ['Error', 'occurred', 'timeout']
```

#### Encoder
```python
from src.preprocessing.encoder import Encoder

encoder = Encoder()
encoded = encoder.encode_log({'level': 'ERROR', 'source': 'kernel'})
```

### src.mining

#### FrequentPatternMining
```python
from src.mining.frequent_pattern import FrequentPatternMining

miner = FrequentPatternMining(min_support=0.1)
transactions = [{'error', 'timeout'}, {'error', 'retry'}, ...]
patterns = miner.find_patterns(transactions)
```

#### AssociationRuleMining
```python
from src.mining.association_rules import AssociationRuleMining

rule_miner = AssociationRuleMining(min_confidence=0.7)
rules = rule_miner.generate_rules(patterns)
```

### src.anomaly_detection

#### StatisticalDetector
```python
from src.anomaly_detection.statistical_detector import StatisticalDetector
import numpy as np

detector = StatisticalDetector(threshold=3.0)
data = np.array([1, 2, 3, 100])
anomalies = detector.detect_zscore(data)
# Returns: [False, False, False, True]
```

#### MLDetector
```python
from src.anomaly_detection.ml_detector import MLDetector

detector = MLDetector(model_path='models/anomaly_detector.h5')
predictions = detector.detect(data, threshold=0.5)
```

#### EnsembleDetector
```python
from src.anomaly_detection.ensemble_detector import EnsembleDetector

ensemble = EnsembleDetector([detector1, detector2, detector3])
anomalies = ensemble.detect(data, voting='majority')
```

### src.storage

#### ElasticsearchHandler
```python
from src.storage.elasticsearch_handler import ElasticsearchHandler

es = ElasticsearchHandler(hosts=['localhost:9200'])
es.index_logs(logs)
results = es.search({'query': {'match': {'level': 'ERROR'}}})
```

#### StorageManager
```python
from src.storage.storage_manager import StorageManager

manager = StorageManager()
manager.register_backend('es', es_handler)
manager.save(logs, backend='es')
```

### src.visualization

#### Dashboard
```python
from src.visualization.dashboard import Dashboard

dashboard = Dashboard(framework='streamlit')
dashboard.start()
dashboard.add_metric('Total Logs', 1000)
dashboard.add_chart('Error Distribution', data)
```

#### AlertManager
```python
from src.visualization.alert_manager import AlertManager

alerts = AlertManager()
alerts.create_alert(condition='level == CRITICAL', action='notify')
alerts.send_notification('email', 'Critical issue detected')
```

## Utility Functions

### Metrics
```python
from src.utils.metrics import Metrics, Timer

# Calculate predictions
metrics = Metrics.calculate_precision_recall(tp=100, fp=10, fn=5)

# Time operations
with Timer('My Operation') as timer:
    # Do work
    pass
elapsed = timer.elapsed()
```

### Validators
```python
from src.utils.validators import Validators

if Validators.validate_log(log):
    print("Valid log")
```

### Helpers
```python
from src.utils.helpers import safe_get, merge_dicts

value = safe_get(config, 'database.host', 'localhost')
combined = merge_dicts(dict1, dict2)
```

## Configuration

All settings in `config/constants.py`:

```python
from config.constants import (
    BATCH_SIZE,
    ANOMALY_THRESHOLD,
    KAFKA_TOPIC_LOGS,
    ELASTICSEARCH_HOSTS,
)
```

## Error Handling

Most functions log errors using Python's logger:

```python
import logging

logger = logging.getLogger(__name__)
# Logs will appear in logs/app.log and console
```
