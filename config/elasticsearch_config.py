"""Elasticsearch configuration module."""

from config.constants import ELASTICSEARCH_HOSTS, ELASTICSEARCH_INDEX_PREFIX

ELASTICSEARCH_CONFIG = {
    'hosts': ELASTICSEARCH_HOSTS,
    'index': ELASTICSEARCH_INDEX_PREFIX,
    'timeout': 20,
}

INDEX_SETTINGS = {
    'settings': {
        'number_of_shards': 1,
        'number_of_replicas': 0,
    },
    'mappings': {
        'properties': {
            'timestamp': {'type': 'date'},
            'message': {'type': 'text'},
            'level': {'type': 'keyword'},
            'source': {'type': 'keyword'},
        }
    }
}
