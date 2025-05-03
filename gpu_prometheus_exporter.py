#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import threading
import logging
from datetime import datetime

# Prometheus 的 Python 客户端
from prometheus_client import start_http_server, Gauge

from monitor import parallel_collect_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ========================
# 1) 定义 Prometheus 指标
# ========================
cpu_usage_gauge = Gauge('system_cpu_usage_percent', 'CPU Usage Percentage')
cpu_power_gauge = Gauge('system_cpu_power_draw_watts', 'CPU Power Draw (W)')
dram_usage_gauge = Gauge('system_dram_usage_percent', 'DRAM Usage Percentage')
dram_power_gauge = Gauge('system_dram_power_draw_watts', 'DRAM Power Draw (W)')

# GPU 指标：每块 GPU 用 gpu_index label 区分
gpu_power_gauge     = Gauge('gpu_power_draw_watts', 'GPU Power Draw (W)', ['gpu_index'])
gpu_util_gpu_gauge  = Gauge('gpu_utilization_percent', 'GPU Core Utilization (%)', ['gpu_index'])
gpu_util_mem_gauge  = Gauge('gpu_memory_util_percent', 'GPU Memory Utilization (%)', ['gpu_index'])
gpu_temp_gauge      = Gauge('gpu_temperature_celsius', 'GPU Temperature (C)', ['gpu_index', 'temp_type'])
gpu_clk_gr_gauge    = Gauge('gpu_clock_graphics_mhz', 'GPU Graphics Clock (MHz)', ['gpu_index'])
gpu_clk_mem_gauge   = Gauge('gpu_clock_memory_mhz',   'GPU Memory Clock (MHz)',    ['gpu_index'])
gpu_clk_sm_gauge    = Gauge('gpu_clock_sm_mhz',       'GPU SM Clock (MHz)',        ['gpu_index'])



def collect_metrics(interval=5.0):
    """
    后台线程循环采集硬件指标，并更新到 Prometheus 的 Gauges 中
    """
    while True:
        try:
            metrics = parallel_collect_metrics()

            # ================== CPU & DRAM ==================
            cpu_usage = metrics.get('cpu_usage', None)   # e.g. 30.0
            cpu_power = metrics.get('cpu_power', None)   # e.g. "50.2" or "N/A"
            dram_usage = metrics.get('dram_usage', None) # e.g. 40.3
            dram_power = metrics.get('dram_power', None) # e.g. "12.5" or "N/A"
            gpu_info_list = metrics.get('gpu_info', [])

            # 1) CPU Usage
            if cpu_usage is not None and cpu_usage != "N/A":
                cpu_usage_gauge.set(float(cpu_usage))

            # 2) CPU Power (若值里可能有 " W" 则同样 .replace)
            if cpu_power and cpu_power != "N/A":
                # 如果 cpu_power 本身是数字字符串，直接 float 即可
                # 若发现还有后缀 " W" 可以这样：
                cpu_power_clean = cpu_power.replace(" W", "").strip()
                cpu_power_gauge.set(float(cpu_power_clean))

            # 3) DRAM Usage
            if dram_usage is not None and dram_usage != "N/A":
                dram_usage_gauge.set(float(dram_usage))

            # 4) DRAM Power
            if dram_power and dram_power != "N/A":
                dram_power_clean = dram_power.replace(" W", "").strip()
                dram_power_gauge.set(float(dram_power_clean))

            # ================== GPU Info ==================
            for gpu in gpu_info_list:
                index_str = str(gpu.get('index', 0))

                # ---- GPU PowerDraw (形如 "31.64 W") ----
                power_draw = gpu.get('power.draw [W]', None)
                if power_draw and power_draw != "N/A":
                    # 去掉 " W"
                    pd = power_draw.replace(" W", "").strip()
                    # 如果 pd 可能是 "", 要小心处理
                    if pd:
                        gpu_power_gauge.labels(gpu_index=index_str).set(float(pd))

                # ---- GPU Util Core (形如 "0 %")
                util_gpu = gpu.get('utilization.gpu [%]', None)
                if util_gpu and util_gpu != "N/A":
                    ug = util_gpu.replace(" %", "").strip()  # 移除后缀
                    if ug:
                        gpu_util_gpu_gauge.labels(gpu_index=index_str).set(float(ug))

                # ---- GPU Util Mem (形如 "0 %")
                util_mem = gpu.get('utilization.memory [%]', None)
                if util_mem and util_mem != "N/A":
                    um = util_mem.replace(" %", "").strip()
                    if um:
                        gpu_util_mem_gauge.labels(gpu_index=index_str).set(float(um))


                #  分两种：temperature.gpu => 'core' label, temperature.memory => 'mem' label
                temp_gpu = gpu.get('temperature.gpu', None)
                if temp_gpu and temp_gpu != "N/A":

                    tg = temp_gpu.strip()
                    if tg:
                        gpu_temp_gauge.labels(gpu_index=index_str, temp_type='core').set(float(tg))

                temp_mem = gpu.get('temperature.memory', None)
                if temp_mem and temp_mem != "N/A":
                    tm = temp_mem.strip()
                    if tm:
                        gpu_temp_gauge.labels(gpu_index=index_str, temp_type='mem').set(float(tm))


                clk_gr = gpu.get('clocks.current.graphics [MHz]', None)
                if clk_gr and clk_gr != "N/A":
                    cg = clk_gr.replace(" MHz", "").strip()
                    if cg:
                        gpu_clk_gr_gauge.labels(gpu_index=index_str).set(float(cg))

                clk_mem = gpu.get('clocks.current.memory [MHz]', None)
                if clk_mem and clk_mem != "N/A":
                    cm = clk_mem.replace(" MHz", "").strip()
                    if cm:
                        gpu_clk_mem_gauge.labels(gpu_index=index_str).set(float(cm))

                clk_sm = gpu.get('clocks.current.sm [MHz]', None)
                if clk_sm and clk_sm != "N/A":
                    cs = clk_sm.replace(" MHz", "").strip()
                    if cs:
                        gpu_clk_sm_gauge.labels(gpu_index=index_str).set(float(cs))

            logging.info("Metrics updated successfully.")

        except Exception as e:
            logging.error(f"Error while collecting metrics: {e}")

        # 等待下一次采集
        time.sleep(interval)

def main():
    # 启动 Prometheus 的 HTTP server，监听端口 8000
    start_http_server(8000)
    logging.info("Prometheus metrics endpoint started on port 8000")

    # 后台线程持续收集
    collector_thread = threading.Thread(
        target=collect_metrics, args=(5.0,), daemon=True
    )
    collector_thread.start()

    # 主线程保持存活
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
