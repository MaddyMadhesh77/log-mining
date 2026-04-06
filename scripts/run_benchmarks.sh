#!/bin/bash
# Run benchmarks

echo "Running benchmarks..."

python -m pytest tests/ -v --benchmark-only

echo "Benchmarks complete"
