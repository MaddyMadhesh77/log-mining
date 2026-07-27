# LogSense AI — Large-Scale Software Log Pattern Mining and Anomaly Detection

A production-grade, real-time Big Data pipeline for detecting anomalies in
distributed system logs using Apache Kafka, Apache Spark, pattern mining
algorithms, and an Isolation Forest model with statistically calibrated
thresholding.

---

## Problem Statement

Modern distributed systems such as Hadoop HDFS generate millions of log lines
per day across hundreds of nodes. These logs contain critical signals about
system health — pipeline failures, data corruption, replication errors, and
node crashes. However, the sheer volume of log data makes manual inspection
infeasible, and static rule-based alerting fails to capture complex,
multi-event failure patterns that emerge only across sequences of operations.

The absence of labeled training data in production environments makes
supervised learning impractical. There is a clear need for an unsupervised,
scalable pipeline that can ingest raw log streams in real time, extract
behavioral patterns, and identify anomalous blocks without requiring
pre-annotated failure records.

---

## Motivation

Log anomaly detection is a foundational capability for site reliability
engineering (SRE) and distributed systems operations. Early detection of
anomalous behavior directly reduces mean time to detection (MTTD) and prevents
cascading failures. This project addresses the problem end-to-end — from raw
log ingestion to real-time visual alerting — using only open-source Big Data
tooling, demonstrating that enterprise-grade anomaly detection can be built
without proprietary infrastructure.

---

## Solution Overview

LogSense AI processes raw HDFS system logs through a multi-stage pipeline:
streaming ingestion via Kafka, distributed parsing via Spark, unsupervised
pattern mining via three complementary algorithms, feature engineering, and
anomaly scoring via Isolation Forest with a Peak Over Threshold (POT)
calibrated decision boundary. All results are served through a FastAPI backend
and visualized on a live HTML dashboard.

---

## System Architecture

```
HDFS Log File (11.1M lines)
        |
        v
[ Kafka Producer ]
  ingestion/kafka_producer.py
  Topic: hdfs-raw-logs
        |
        v
[ Spark Structured Streaming ]
  processing/spark_streaming.py
  - Regex parsing: block_id, event_id, pid, level, component
  - Template mapping: raw content -> EventID (E1-E29)
  - Output: HDFS Parquet at /logsense/parsed_logs/
  - Sink: Elasticsearch index (logsense-logs)
        |
        v
[ Pattern Mining Layer ]  (three parallel algorithms)
  |                   |                        |
  v                   v                        v
FP-Growth          PrefixSpan           BisectingKMeans
(MLlib)            (MLlib)              (MLlib)
Frequent event     Ordered event        Block behavioral
co-occurrence      sequences per        clustering into
itemsets per       block -> deviation   k=8 groups ->
block -> rarity    score                outlier score
score
  |                   |                        |
  +-------------------+------------------------+
                       |
                       v
          [ Feature Builder ]
          features/feature_builder.py
          31 features per block:
          - fp_rarity_score
          - seq_deviation_score
          - cluster_outlier_score
          - cluster_id, total_events_norm,
            unique_event_count, log_span_secs_norm
          - E1_norm ... E29_norm
                       |
                       v
          [ Isolation Forest Model ]
          anomaly/isolation_forest.py
          sklearn IsolationForest
          575,061 samples x 31 features
                       |
                       v
          [ POT Threshold Calibration ]
          Generalized Pareto Distribution (GPD)
          fitted on score tail (q0=0.90)
          FPR target < 1%
                       |
                       v
          [ FastAPI Backend ]           [ Elasticsearch ]
          api/main.py                   logsense-anomalies index
          9 REST endpoints              block search + alert store
                       |
                       v
          [ HTML Dashboard ]
          dashboard/logsense-dashboard.html
          Chart.js visualizations
          Live polling every 10 seconds
```

---

## Algorithms

### FP-Growth (Frequent Pattern Mining)
Treats each log block as a transaction of EventIDs and mines all frequent
itemsets above a minimum support threshold using a compressed FP-Tree
structure. The inverse frequency of a block's event combination relative to
the mined itemsets produces the `fp_rarity_score` feature — blocks exhibiting
rare event co-occurrences receive a high rarity score, signaling potential
anomalous behavior.

### PrefixSpan (Sequential Pattern Mining)
Extends pattern mining to ordered sequences, recognizing that the order of
events within a block carries diagnostic meaning. PrefixSpan uses
prefix-projected databases to efficiently enumerate all frequent ordered
sequences. The `seq_deviation_score` for each block quantifies how much its
event ordering deviates from the most common normal sequences observed across
the dataset.

### BisectingKMeans (Clustering)
Groups blocks into k=8 behavioral clusters based on normalized event frequency
vectors. BisectingKMeans recursively bisects the largest cluster until k
clusters are formed, producing tight, well-separated groups. The distance of
each block from its cluster centroid becomes the `cluster_outlier_score`
feature. Clusters with high inter-cluster anomaly ratios directly reveal
structurally distinct failure modes.

### Isolation Forest (Anomaly Detection)
An ensemble of 100 isolation trees scores each block by the average path
length required to isolate it. Anomalous blocks — characterized by rare,
deviant feature vectors — are isolated in fewer splits, yielding a high
anomaly score. The model is entirely unsupervised; ground truth labels are
used only during evaluation and never during training.

### Peak Over Threshold (POT) — Threshold Calibration
Rather than using a fixed or percentile-based threshold, LogSense AI fits a
Generalized Pareto Distribution (GPD) to the tail of the anomaly score
distribution using Extreme Value Theory. The threshold is derived at the score
where the probability of a false positive drops below 1%, producing a
statistically principled, self-calibrating decision boundary that adapts to
the score distribution of each pipeline run.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Distributed Storage | Apache Hadoop HDFS |
| Message Streaming | Apache Kafka |
| Stream Processing | Apache Spark Structured Streaming |
| Pattern Mining | Apache Spark MLlib (FP-Growth, PrefixSpan, BisectingKMeans) |
| Anomaly Detection | scikit-learn IsolationForest |
| Threshold Calibration | SciPy (Generalized Pareto Distribution) |
| Search and Indexing | Elasticsearch |
| REST API | FastAPI + Uvicorn |
| Data Processing | pandas, NumPy |
| Visualization | HTML5 + Chart.js |
| Runtime | Python 3.10+, WSL2 (Ubuntu) |

---

## Project Structure

```
logsense-ai/
├── ingestion/
│   └── kafka_producer.py        # Streams raw log lines to Kafka
├── processing/
│   └── spark_streaming.py       # Spark parsing, template mapping, HDFS sink
├── mining/
│   ├── fp_growth.py             # FP-Growth frequent itemset mining
│   ├── prefixspan.py            # PrefixSpan sequential pattern mining
│   └── clustering.py            # BisectingKMeans cluster analysis
├── features/
│   └── feature_builder.py       # Assembles 31-feature matrix per block
├── anomaly/
│   └── isolation_forest.py      # IF training, POT thresholding, scoring
├── evaluation/
│   └── metrics.py               # Precision, Recall, F1, confusion matrix
├── api/
│   └── main.py                  # FastAPI REST endpoints
├── dashboard/
│   └── logsense-dashboard.html  # Live visualization dashboard
├── config/
│   └── settings.py              # Kafka, HDFS, ES, API configuration
├── utils/
│   └── logger.py                # Structured logging utility
└── data/
    ├── raw/                     # Input: HDFS_2k.log or full log file
    ├── output/                  # Pipeline outputs: CSVs, models, metrics
    └── models/                  # Saved IF model and threshold JSON
```

---

## Setup and Execution

### Prerequisites
- Hadoop 3.x with HDFS running (`start-dfs.sh`)
- Apache Kafka with Zookeeper running
- Elasticsearch 8.x running on port 9200
- Python 3.10+ with virtual environment

### Installation

```bash
git clone https://github.com/Manoj-dj/Large-Scale-Software-Log-Pattern-Mining.git
cd Large-Scale-Software-Log-Pattern-Mining
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Pipeline

```bash
# Step 1 — Create HDFS directories
hdfs dfs -mkdir -p /logsense/parsed_logs /logsense/patterns /logsense/features /logsense/anomalies

# Step 2 — Start Spark consumer (Terminal 1)
python -m processing.spark_streaming

# Step 3 — Start Kafka producer (Terminal 2)
python -m ingestion.kafka_producer --lines 200000

# Step 4 — Run mining and feature engineering (after streaming completes)
python -m mining.fp_growth
python -m mining.prefixspan
python -m mining.clustering
python -m features.feature_builder

# Step 5 — Train Isolation Forest and apply POT threshold
python -m anomaly.isolation_forest

# Step 6 — Start API and open dashboard
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
# Open: dashboard/logsense-dashboard.html in browser
```

### Important Notes
- Always delete the Spark checkpoint before a fresh run:
  `rm -rf /tmp/logsense_checkpoint/`
- Ensure `startingOffsets` is set to `"earliest"` in `spark_streaming.py`
  when replaying Kafka messages after a restart.

---

## Dashboard Sections

| Section | Content |
|---|---|
| Overview | KPI cards, anomaly gauge, system status, pipeline architecture |
| Anomaly Detection | Score distribution, percentile curve, confusion matrix, top anomalous blocks |
| Pattern Mining | FP-Growth itemsets, PrefixSpan sequences, deviation score histogram |
| Cluster Analysis | Cluster anomaly ratios, size distribution, per-cluster risk table |
| Live Stream | Real-time log feed, anomaly alert table, Kafka topic status |
| Model Info | Feature importance, training summary, POT threshold parameters |

---

## Dataset

**Source:** HDFS (Hadoop Distributed File System) system logs from the
publicly available HDFS log dataset (Loghub).
**Scale:** 11.1 million raw log lines, 575,061 unique block operations.
**Format:** `[Date] [Time] [PID] [Level] [Component]: [Content]`

---


# log-mining
# log-mining
