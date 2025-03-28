#!/bin/bash
echo hostname
hostname

# 监控功能
python monitor.py monitor \
    -n "test_complex" \
    -t 1 \
    -cmd "python test_complex.py" \
    -o "csv"


