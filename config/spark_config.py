"""Spark configuration module."""

from config.constants import SPARK_MASTER, SPARK_APP_NAME, NUM_PARTITIONS

SPARK_CONFIG = {
    'spark.master': SPARK_MASTER,
    'spark.app.name': SPARK_APP_NAME,
    'spark.sql.shuffle.partitions': NUM_PARTITIONS,
    'spark.default.parallelism': NUM_PARTITIONS,
    'spark.driver.memory': '2g',
    'spark.executor.memory': '2g',
}
