#!/bin/bash
echo hostname
hostname

# 画图功能
python monitor.py plot \
    -t "test_complex_20250326_154839.csv" \
    -f "csv"