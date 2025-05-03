import os
import csv
import subprocess
import time
import argparse
import psutil
import mysql.connector
import logging
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio  # 导入io模块来保存为HTML文件
import threading
from datetime import datetime
from deprecated import deprecated
from typing import Callable, Optional, Dict
import functools
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import shlex

# 用于保存每个函数的执行时间
execution_times = {}
execution_times['elapsed_time'] = []

# 数据库连接配置信息
class Config:
    host = "10.120.17.137"
    user = "hhz"
    password = "Bigben077"
    database = "monitor"

# 设置日志配置
logging.basicConfig(
    filename="monitor.log",  
    level=logging.DEBUG,  
    format="%(asctime)s - %(levelname)s - %(message)s",  
    datefmt="%Y-%m-%d %H:%M:%S"  
)

# 全局变量，用于记录插入的记录数
inserted_count = -1

def calculate_metrics(file_path):
    """
    计算CSV文件中的统计信息和能耗
    先按gpu_index分组后再计算GPU相关指标。
    参数:
        file_path (str): CSV文件路径
    返回:
        dict: 包含CPU/DRAM统计信息、各GPU统计信息、总时间和能耗的字典
    """
    # 读取CSV文件
    df = pd.read_csv(file_path)
    # 将 "N/A" 替换为 NaN，不删除整行
    df.replace("N/A", np.nan, inplace=True)
    # 转换时间戳为 datetime 格式
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # 计算总时间（秒）
    total_time = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds()
    # 定义需要清洗的所有列
    cols_to_clean = ['cpu_usage', 
                     'cpu_power_draw', 
                     'dram_usage', 
                     'dram_power_draw',
                     'gpu_power_draw', 
                     'utilization_gpu', 
                     'utilization_memory', 
                     'pcie_link_gen_current', 
                     'pcie_link_width_current',
                     'temperature_gpu', 
                     'temperature_memory', 
                     'clocks_gr', 
                     'clocks_mem', 
                     'clocks_sm']
    # 清洗：去除百分比、单位等非数值字符，并转换为数值
    for col in cols_to_clean:
        if col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].str.replace(r'[^\d.]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    # 定义单位映射
    unit_map = {
        'cpu_usage': ' %',
        'cpu_power_draw': ' W',
        'dram_usage': ' %',
        'dram_power_draw': ' W',
        'gpu_power_draw': ' W',
        'utilization_gpu': ' %',
        'utilization_memory': ' %',
        'pcie_link_gen_current': '',
        'pcie_link_width_current': '',
        'temperature_gpu': ' °C',
        'temperature_memory': ' °C',
        'clocks_gr': ' MHz',
        'clocks_mem': ' MHz',
        'clocks_sm': ' MHz'
    }
    
    def compute_stat(series, unit):
        """计算平均、最大、最小、众数；若整列全为NaN则返回 'N/A'"""
        if series.dropna().empty:
            return {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'}
        else:
            mode_series = series.mode(dropna=True)
            mode_val = f"{mode_series.iloc[0]:.2f}{unit}" if not mode_series.empty else "N/A"
            return {
                'mean': f"{series.mean(skipna=True):.2f}{unit}",
                'max': f"{series.max(skipna=True):.2f}{unit}",
                'min': f"{series.min(skipna=True):.2f}{unit}",
                'mode': mode_val
            }
    
    # 计算 CPU 和 DRAM 相关统计指标
    cpu_dram_columns = ['cpu_usage', 'cpu_power_draw', 'dram_usage', 'dram_power_draw']
    cpu_dram_stats = {}
    for col in cpu_dram_columns:
        if col in df.columns:
            unit = unit_map.get(col, '')
            cpu_dram_stats[col] = compute_stat(df[col], unit)
    
    # 对 GPU 相关指标先按 gpu_index 分组后计算
    gpu_columns = ['gpu_power_draw', 'utilization_gpu', 'utilization_memory',
                   'pcie_link_gen_current', 'pcie_link_width_current',
                   'temperature_gpu', 'temperature_memory', 
                   'clocks_gr', 'clocks_mem', 'clocks_sm']
    gpu_stats = {}
    if 'gpu_index' in df.columns:
        for gpu_idx, group in df.groupby('gpu_index'):
            gpu_stats[gpu_idx] = {}
            for col in gpu_columns:
                if col in group.columns:
                    unit = unit_map.get(col, '')
                    gpu_stats[gpu_idx][col] = compute_stat(group[col], unit)
    
    # --- 能耗计算部分 ---
    # 为 CPU 和 DRAM 能耗计算先对整体数据按时间戳去重
    df_unique = df.drop_duplicates(subset=['timestamp']).copy()
    df_unique['time_interval'] = df_unique['timestamp'].diff().dt.total_seconds().fillna(0)
    
    if df_unique['cpu_power_draw'].dropna().empty:
        cpu_energy = 'N/A'
    else:
        cpu_energy_val = (df_unique['cpu_power_draw'] * df_unique['time_interval']).sum(skipna=True)
        cpu_energy = f"{cpu_energy_val:.2f} J"
    
    if df_unique['dram_power_draw'].dropna().empty:
        dram_energy = 'N/A'
    else:
        dram_energy_val = (df_unique['dram_power_draw'] * df_unique['time_interval']).sum(skipna=True)
        dram_energy = f"{dram_energy_val:.2f} J"
    
    energy_consumption = {
        'cpu_energy': cpu_energy,
        'dram_energy': dram_energy,
        'gpu_energy': {}
    }
    
    # GPU能耗：对于每个 GPU 按 gpu_index 分组后，先对该组数据按时间戳去重再计算时间间隔
    if 'gpu_index' in df.columns:
        for gpu_idx, group in df.groupby('gpu_index'):
            group_unique = group.drop_duplicates(subset=['timestamp']).copy()
            group_unique['time_interval'] = group_unique['timestamp'].diff().dt.total_seconds().fillna(0)
            if group_unique['gpu_power_draw'].dropna().empty:
                energy_consumption['gpu_energy'][gpu_idx] = 'N/A'
            else:
                gpu_energy_val = (group_unique['gpu_power_draw'] * group_unique['time_interval']).sum(skipna=True)
                energy_consumption['gpu_energy'][gpu_idx] = f"{gpu_energy_val:.2f} J"
    
    # 计算总能耗（累加有效的CPU、DRAM和各GPU能耗）
    total_energy_val = 0.0
    valid = False
    for energy in [cpu_energy, dram_energy]:
        if energy != 'N/A':
            total_energy_val += float(energy.split()[0])
            valid = True
    for val in energy_consumption['gpu_energy'].values():
        if val != 'N/A':
            total_energy_val += float(val.split()[0])
            valid = True
    total_energy = f"{total_energy_val:.2f} J" if valid else 'N/A'
    energy_consumption['total_energy'] = total_energy
    # --- 能耗计算结束 ---
    
    return {
        'cpu_dram_stats': cpu_dram_stats,
        'gpu_stats': gpu_stats,
        'total_time': f"{total_time:.2f} 秒",
        'energy_consumption': energy_consumption
    }

# 用于计算函数的执行时间
def timing_decorator(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()  # 记录开始时间
        result = func(*args, **kwargs)  # 调用原函数
        end_time = time.time()  # 记录结束时间
        execution_time = end_time - start_time  # 计算执行时间

        # 记录每次执行的时间
        if func.__name__ not in execution_times:
            execution_times[func.__name__] = []
        execution_times[func.__name__].append(execution_time)
        
        print(f"Function '{func.__name__}' executed in {execution_time:.4f} seconds")
        return result
    return wrapper

# 用于获取函数的平均执行时间
def get_average_time(func_name):
    if func_name in execution_times:
        times = execution_times[func_name]
        average_time = sum(times) / len(times)
        return average_time
    else:
        return None
    
# 用于获取函数的最大执行时间
def get_max_time(func_name):
    if func_name in execution_times:
        return max(execution_times[func_name])
    else:
        return None

# 用于监控函数运行时资源占用的装饰器工厂
def monitor_resources(
    log_file: str = "resource_monitor.log",
    monitor_cpu: bool = True,
    monitor_mem: bool = True,
    monitor_disk: bool = True,
    disk_device: str = "sda3"
):
    """
    监控函数运行时资源占用的装饰器工厂
    Args:
        log_file: 监控日志文件路径
        monitor_cpu: 是否监控CPU
        monitor_mem: 是否监控内存
        monitor_disk: 是否监控磁盘
        disk_device: 监控的磁盘设备名
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 初始化监控数据
            process = psutil.Process()
            disk_before = psutil.disk_io_counters(perdisk=True).get(disk_device, None)
            cpu_samples = []
            mem_samples = []

            # 启动后台采样线程
            def sampler(stop_event):
                while not stop_event.is_set():
                    if monitor_cpu:
                        cpu_samples.append(process.cpu_percent(interval=0.1))
                    if monitor_mem:
                        mem_samples.append(process.memory_info().rss)
                    time.sleep(0.5)  # 每0.5秒采样一次

            stop_event = threading.Event()
            sampler_thread = threading.Thread(target=sampler, args=(stop_event,))
            sampler_thread.start()

            # 执行目标函数
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
            finally:
                # 停止采样并计算指标
                stop_event.set()
                sampler_thread.join(timeout=1)
                duration = time.time() - start_time

                # 收集最终数据
                disk_after = psutil.disk_io_counters(perdisk=True).get(disk_device, None)
                
                # 计算统计指标
                stats = {
                    "function": func.__name__,
                    "duration": f"{duration:.2f}s",
                    "cpu_avg": None,
                    "cpu_max": None,
                    "mem_avg": None,
                    "mem_max": None,
                    "disk_read": None,
                    "disk_write": None
                }

                if monitor_cpu and cpu_samples:
                    stats.update({
                        "cpu_avg": f"{sum(cpu_samples)/len(cpu_samples):.1f}%",
                        "cpu_max": f"{max(cpu_samples):.1f}%"
                    })

                if monitor_mem and mem_samples:
                    stats.update({
                        "mem_avg": f"{sum(mem_samples)/len(mem_samples)/1024/1024:.1f}MB",
                        "mem_max": f"{max(mem_samples)/1024/1024:.1f}MB"
                    })

                if monitor_disk and disk_before and disk_after:
                    stats.update({
                        "disk_read": f"{(disk_after.read_bytes - disk_before.read_bytes)/1024/1024:.1f}MB",
                        "disk_write": f"{(disk_after.write_bytes - disk_before.write_bytes)/1024/1024:.1f}MB"
                    })

                # 记录日志
                log_message = (
                    f"Resource Report - {func.__name__}\n"
                    f"Duration: {stats['duration']}\n"
                    f"CPU Usage (avg/max): {stats['cpu_avg']} / {stats['cpu_max']}\n"
                    f"Memory Usage (avg/max): {stats['mem_avg']} / {stats['mem_max']}\n"
                    f"Disk I/O (read/write): {stats['disk_read']} / {stats['disk_write']}\n"
                    "----------------------------------------"
                )
                with open(log_file, "a") as f:
                    f.write(log_message + "\n")
                logging.info(f"Resource usage logged to {log_file}")

            return result
        return wrapper
    return decorator
    
def run_task(command):
    """
    执行指定的命令并等待其完成。
    参数:
    command (str): 要执行的命令（字符串形式）
    返回:
    int: 命令的退出码
    """
    try:
        # 将命令字符串拆分为列表 windows可以不做拆分
        cmd_list = shlex.split(command)
        process = subprocess.Popen(cmd_list, shell=False)
        process.wait()
        return process.returncode
    except Exception as e:
        logging.error(f"Error running task command: {e}")
        return -1

@monitor_resources(
    log_file="monitor_stats.log",
    monitor_cpu=True,
    monitor_mem=True,
    monitor_disk=False,
    disk_device="nvme0n1"  # 根据实际磁盘设备修改
)
def monitor_stats(task_name, time_interval, timestamp, stop_event, output_format="csv"):
    """
    监控CPU和GPU的使用情况并将数据保存到MySQL或者CSV。
    参数:
    task_name (str): 任务名称
    time_interval (int): 采样时间间隔（秒）
    timestamp (str): 时间戳（用于记录文件名）
    stop_event (threading.Event): 用于停止监控的事件
    output_format (str): 输出格式（默认为CSV）
    """
    while not stop_event.is_set():
        try:
            start_time = time.time() # 记录开始时间
            # 用于插入数据的时间戳 保留1位小数
            time_stamp_insert = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]
            # 并行采集所有指标
            metrics = parallel_collect_metrics()
            # 有效性检查
            if metrics["gpu_info"] is None:
                logging.warning("No GPU info available, skipping data collection.")
                time.sleep(time_interval)
                continue
            if metrics["cpu_usage"] is None:
                logging.warning("Failed to get CPU info, skipping data collection.")
                time.sleep(time_interval)
                continue           
            # 后续处理保持不变...
            other_metrics = [metrics["cpu_power"], metrics["dram_power"], metrics["dram_usage"]]

            if output_format == "csv":
                save_to_csv(task_name, metrics["cpu_usage"], metrics["gpu_info"], 
                           other_metrics, timestamp, time_stamp_insert)
            elif output_format == "mysql":
                save_to_mysql(task_name, metrics["cpu_usage"], metrics["gpu_info"], 
                             other_metrics, timestamp, time_stamp_insert)

            if inserted_count % 10 == 0 or inserted_count == 1:
                logging.info(f"Total records inserted so far: {inserted_count}")

            elapsed_time = time.time() - start_time
            execution_times['elapsed_time'].append(elapsed_time)
            remaining_time = max(0, time_interval - elapsed_time)
            time.sleep(remaining_time)

        except Exception as e:
            logging.error(f"Unexpected error in monitor_stats: {e}")
            time.sleep(time_interval)       

def get_gpu_info():
    """
    获取基本GPU信息，返回一个字典列表，每个字典包含一个GPU的信息
    """
    command = [
        "nvidia-smi",
        "--query-gpu=name,index,power.draw,utilization.gpu,utilization.memory,"
        "pcie.link.gen.current,pcie.link.width.current,temperature.gpu,"
        "temperature.memory,clocks.gr,clocks.mem,clocks.current.sm",
        "--format=csv"
    ]
    try:
        result = subprocess.check_output(command, shell=False).decode('utf-8')
        lines = result.strip().split("\n")
        headers = lines[0].split(", ")
        gpu_data_list = []
        for line in lines[1:]:
            if not line.strip():
                continue
            values = line.split(", ")
            gpu_data = {}
            for i, header in enumerate(headers):
                gpu_data[header] = values[i]
            gpu_data_list.append(gpu_data)
        return gpu_data_list
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running basic command: {e}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error in run_basic_info: {e}")
        return []

def get_cpu_usage_info():
    """
    获取CPU信息
    返回:
    float: CPU使用率
    """
    try:
        cpu_usage = psutil.cpu_percent(interval=0.050)
        return cpu_usage
    except Exception as e:
        logging.error(f"Error getting CPU info: {e}")
        return None

def get_cpu_power_info(sample_interval=0.050):
    """
    获取 CPU 功耗（两次采样差值计算，单位：瓦特）
    参数:sample_interval (float): 采样间隔（秒）
    返回:float: 平均功耗（瓦特）或 "N/A" 表示无法获取功耗
    """
    try:
        powercap_path = "/sys/class/powercap"
        if not os.path.exists(powercap_path):
            return "N/A"
        
        domains = []
        for entry in os.listdir(powercap_path):
            if entry.startswith("intel-rapl:") and ":" not in entry[len("intel-rapl:"):]:
                domain_path = os.path.join(powercap_path, entry)
                energy_path = os.path.join(domain_path, "energy_uj")
                
                if os.path.exists(energy_path):
                    with open(energy_path, "r") as f:
                        energy_start = int(f.read().strip())
                    timestamp_start = time.time()
                    
                    domains.append({
                        "path": energy_path,
                        "energy_start": energy_start,
                        "timestamp_start": timestamp_start})

        if not domains:
            return "N/A"
        time.sleep(sample_interval)

        total_power_w = 0.0
        for domain in domains:
            with open(domain["path"], "r") as f:
                energy_end = int(f.read().strip())
            timestamp_end = time.time()
            delta_time = timestamp_end - domain["timestamp_start"]
            if delta_time <= 0:
                continue  # 避免除以零或负数
            
            delta_energy_uj = energy_end - domain["energy_start"]

            # 处理计数器溢出（RAPL 能量计数器为 32/64 位无符号）
            if delta_energy_uj < 0:
                max_energy_path = os.path.join(os.path.dirname(domain["path"]), "max_energy_range_uj")
                if os.path.exists(max_energy_path):
                    with open(max_energy_path, "r") as f:
                        max_energy = int(f.read().strip())
                    delta_energy_uj += max_energy + 1
            
            power_w = (delta_energy_uj * 1e-6) / delta_time  # μJ → J → W
            total_power_w += power_w
        return total_power_w if total_power_w > 0 else "N/A"
    
    except Exception as e:
        logging.error(f"Error getting CPU power info: {e}")
        return "N/A"

def get_dram_usage_info():
    """
    获取DRAM使用情况
    返回:
    float: DRAM使用率
    """
    try:
        info = psutil.virtual_memory()
        dram_usage = info.percent
        return dram_usage
    except Exception as e:
        logging.error(f"Error getting DRAM usage info: {e}")
        return None

def get_dram_power_info(sample_interval=0.050):
    """
    获取 DRAM 功耗（两次采样差值计算，单位：瓦特）
    参数:sample_interval (float): 采样间隔（秒）
    返回:float: 平均功耗（瓦特）或 "N/A" 表示无法获取功耗
    """
    try:
        powercap_path = "/sys/class/powercap"
        if not os.path.exists(powercap_path):
            return "N/A"
        
        domains = []
        for entry in os.listdir(powercap_path):
            domain_path = os.path.join(powercap_path, entry)
            name_path = os.path.join(domain_path, "name")
            if os.path.exists(name_path):
                with open(name_path, "r") as f:
                    name = f.read().strip()
                if name == "dram":
                    energy_path = os.path.join(domain_path, "energy_uj")
                    if os.path.exists(energy_path):
                        with open(energy_path, "r") as f:
                            energy_start = int(f.read().strip())
                        domains.append({
                            "path": energy_path,
                            "energy_start": energy_start,
                            "timestamp_start": time.time()
                        })
        
        if not domains:
            return "N/A"
        time.sleep(sample_interval)
        
        total_power_w = 0.0
        for domain in domains:
            with open(domain["path"], "r") as f:
                energy_end = int(f.read().strip())
            timestamp_end = time.time()
            delta_time = timestamp_end - domain["timestamp_start"]
            if delta_time <= 0:
                continue
            delta_energy_uj = energy_end - domain["energy_start"]
            
            # 处理计数器溢出（RAPL 能量计数器为无符号）
            if delta_energy_uj < 0:
                max_energy_path = os.path.join(os.path.dirname(domain["path"]), "max_energy_range_uj")
                if os.path.exists(max_energy_path):
                    with open(max_energy_path, "r") as f:
                        max_energy = int(f.read().strip())
                    delta_energy_uj += max_energy + 1
            
            # 计算功耗（单位：瓦特）
            power_w = (delta_energy_uj * 1e-6) / delta_time  # μJ → J → W
            total_power_w += power_w
        
        return total_power_w if total_power_w > 0 else "N/A"
    
    except Exception as e:
        logging.error(f"Error getting DRAM power info: {e}", exc_info=True)
        return "N/A"

def parallel_collect_metrics():
    """
    并行收集硬件指标
    """
    metrics = {}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        # 创建任务映射
        futures = {
            executor.submit(get_cpu_usage_info): "cpu_usage",
            executor.submit(get_cpu_power_info): "cpu_power",
            executor.submit(get_dram_power_info): "dram_power",
            executor.submit(get_dram_usage_info): "dram_usage",
            executor.submit(get_gpu_info): "gpu_info"
        }

        # 等待所有任务完成（带超时保护）
        for future in as_completed(futures, timeout=1.5):
            key = futures[future]
            try:
                result = future.result()
                if key == 'gpu_info':
                    gpu_data_list = result
                else:
                    metrics[key] = result
            except Exception as e:
                logging.warning(f"Failed to collect metric: {key} - {str(e)}")
                metrics[key] = None
            
        metrics['gpu_info'] = gpu_data_list

    return metrics

# mysql太久没更新，先不更新
def save_to_mysql(task_name, cpu_usage, gpu_data_list, other_metrics, timestamp, time_stamp_insert):
    """
    将数据保存到MySQL数据库
    参数:
    task_name (str): 任务名称
    cpu_usage (float): CPU使用率
    gpu_data_list (list): 包含GPU信息的字典列表
    timestamp (str): 时间戳（用于表名）
    time_stamp_insert (str): 用于插入数据的时间戳
    """
    try:
        global inserted_count  

        # 连接到MySQL数据库
        mydb = mysql.connector.connect(
            host=Config.host,
            user=Config.user,
            password=Config.password,
            database=Config.database
        )
        cursor = mydb.cursor()

        # 表名格式: task_name_timestamp
        table_name = f"{task_name}_{timestamp}"

        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-incremented record ID',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp of data entry',
            task_name VARCHAR(50) COMMENT 'Name of the task being monitored',
            cpu_usage VARCHAR(50) COMMENT 'CPU usage percentage',
            cpu_power_draw VARCHAR(50) COMMENT 'Power draw of the CPU in watts',
            dram_usage VARCHAR(50) COMMENT 'DRAM usage percentage',
            dram_power_draw VARCHAR(50) COMMENT 'Power draw of the DRAM in watts',
            gpu_name VARCHAR(50) COMMENT 'Name of the GPU',
            gpu_index INT COMMENT 'Index of the GPU',
            gpu_power_draw VARCHAR(50) COMMENT 'Power draw of the GPU in watts',
            utilization_gpu VARCHAR(50) COMMENT 'GPU utilization percentage',
            utilization_memory VARCHAR(50) COMMENT 'Memory utilization percentage of the GPU',
            pcie_link_gen_current VARCHAR(50) COMMENT 'Current PCIe generation of the link',
            pcie_link_width_current VARCHAR(50) COMMENT 'Current width of the PCIe link',
            temperature_gpu VARCHAR(50) COMMENT 'Temperature of the GPU in Celsius',
            temperature_memory VARCHAR(50) COMMENT 'Temperature of the GPU memory in Celsius',
            clocks_gr VARCHAR(50) COMMENT 'Graphics clock frequency',
            clocks_mem VARCHAR(50) COMMENT 'Memory clock frequency',
            clocks_sm VARCHAR(50) COMMENT 'SM clock frequency'
        )
        """
        cursor.execute(create_table_query)

        # 检查表是否创建成功
        if inserted_count == -1:
            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            result = cursor.fetchone()
            if result:
                logging.info(f"Table {table_name} created")
            else:
                logging.error(f"Failed to create table {table_name}")
            inserted_count += 1

        # 插入数据
        insert_query = f"""
        INSERT INTO {table_name}(timestamp, task_name, cpu_usage, cpu_power_draw, dram_usage, dram_power_draw, gpu_name, gpu_index, gpu_power_draw, utilization_gpu, utilization_memory,
                                pcie_link_gen_current, pcie_link_width_current, temperature_gpu, temperature_memory, clocks_gr, clocks_mem, clocks_sm)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for gpu_info in gpu_data_list:
            
            #  GPU温度可能不可用
            temp_gpu = gpu_info.get("temperature.gpu", "N/A")
            temp_memory = gpu_info.get("temperature.memory", "N/A")

            # 构建数据元组，每个元素对应一列数据
            data = (
                time_stamp_insert,                               
                task_name,                                       
                f"{cpu_usage:.2f} %",
                f"{other_metrics[0]:.2f} W", 
                f"{other_metrics[1]:.2f} W",
                f"{other_metrics[2]:.2f} %",                           
                f"{gpu_info.get('name', '')}",                        
                int(gpu_info.get('index', 0)),                   
                f"{gpu_info.get('power.draw [W]', '')}",              
                f"{gpu_info.get('utilization.gpu [%]', '')}",         
                f"{gpu_info.get('utilization.memory [%]', '')}",      
                f"{gpu_info.get('pcie.link.gen.current', '')}",       
                f"{gpu_info.get('pcie.link.width.current', '')}",     
                f"{temp_gpu} °C" if temp_gpu != "N/A" else "N/A",
                f"{temp_memory} °C" if temp_memory != "N/A" else "N/A",
                f"{gpu_info.get('clocks.current.graphics [MHz]', '')}",
                f"{gpu_info.get('clocks.current.memory [MHz]', '')}",
                f"{gpu_info.get('clocks.current.sm [MHz]', '')}"
            )
            cursor.execute(insert_query, data)
            inserted_count += 1

        mydb.commit()
        cursor.close()
        mydb.close()

    except mysql.connector.Error as e:
        logging.error(f"MySQL operation error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in save_to_mysql: {e}")

def save_to_csv(task_name, cpu_usage, gpu_data_list, other_metrics, timestamp, time_stamp_insert):
    """
    将数据保存到CSV文件
    参数:
    task_name (str): 任务名称
    cpu_usage (float): CPU使用率
    gpu_data_list (list): 包含GPU信息的字典列表
    timestamp (str): 时间戳（用于文件名）
    time_stamp_insert (str): 时间戳（用于插入数据）
    """
    try:
        global inserted_count
        # 定义保存数据的目录
        save_dir = os.path.join(os.path.dirname(__file__), 'monitor_data')
        os.makedirs(save_dir, exist_ok=True)  # 如果目录不存在，则创建
        # 生成标准化文件名
        filename = os.path.join(save_dir, f"{task_name}_{timestamp}.csv")
        # 数据写入模式（追加模式）
        write_mode = 'a' if os.path.exists(filename) else 'w'
        with open(filename, mode=write_mode, newline='', encoding='utf-8') as csvfile:
            # 字段顺序与MySQL表结构完全对应
            fieldnames = [
                'timestamp', 
                'task_name', 
                'cpu_usage', 
                'cpu_power_draw', 
                'dram_usage', 
                'dram_power_draw', 
                'gpu_name', 
                'gpu_index', 
                'gpu_power_draw', 
                'utilization_gpu', 
                'utilization_memory', 
                'pcie_link_gen_current', 
                'pcie_link_width_current', 
                'temperature_gpu', 
                'temperature_memory', 
                'clocks_gr', 
                'clocks_mem', 
                'clocks_sm'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # 写入表头（仅新文件需要）
            if write_mode == 'w':
                writer.writeheader()
                if inserted_count == -1:
                    logging.info(f"csv {filename} created")
                    inserted_count += 1
            
            # 批量写入数据
            for gpu_info in gpu_data_list:
                # GPU温度可能不可用
                temp_gpu = gpu_info.get('temperature.gpu', 'N/A')
                temp_memory = gpu_info.get('temperature.memory', 'N/A')

                # 如果为N/A，则显示为N/A，否则显示为浮点数
                cpu_power_draw = f"{other_metrics[0]:.2f} W" if other_metrics[0] != 'N/A' else 'N/A'
                dram_power_draw = f"{other_metrics[1]:.2f} W" if other_metrics[1] != 'N/A' else 'N/A'

                row = {
                    'timestamp': time_stamp_insert,
                    'task_name': task_name,
                    'cpu_usage': f"{cpu_usage:.2f} %",
                    'cpu_power_draw': cpu_power_draw,
                    'dram_power_draw': dram_power_draw,
                    'dram_usage': f"{other_metrics[2]:.2f} %",
                    'gpu_name': gpu_info.get('name', 'N/A'),
                    'gpu_index': int(gpu_info.get('index', 0)),
                    'gpu_power_draw': gpu_info.get('power.draw [W]', 'N/A'),
                    'utilization_gpu': gpu_info.get('utilization.gpu [%]', 'N/A'),
                    'utilization_memory': gpu_info.get('utilization.memory [%]', 'N/A'),
                    'pcie_link_gen_current': gpu_info.get('pcie.link.gen.current', 'N/A'),
                    'pcie_link_width_current': gpu_info.get('pcie.link.width.current', 'N/A'),
                    'temperature_gpu': f"{temp_gpu} °C" if temp_gpu != 'N/A' else "N/A",
                    'temperature_memory': f"{temp_memory} °C" if temp_memory != 'N/A' else "N/A",
                    'clocks_gr': gpu_info.get('clocks.current.graphics [MHz]', 'N/A'),
                    'clocks_mem': gpu_info.get('clocks.current.memory [MHz]', 'N/A'),
                    'clocks_sm': gpu_info.get('clocks.current.sm [MHz]', 'N/A')
                }
                writer.writerow(row)
                inserted_count += 1
            
    except PermissionError as pe:
        logging.error(f"Permission denied for file {filename}: {pe}")
    except csv.Error as ce:
        logging.error(f"CSV formatting error: {ce}")
    except Exception as e:
        logging.error(f"Unexpected error in save_to_csv: {str(e)}")

def fetch_and_plot_data(table_name, format):
    """
    从MySQL数据库或CSV文件中检索数据并绘制图表
    参数:
      table_name (str): 数据表名称或CSV文件名
      format (str): 输入格式（"mysql" 或 "csv"）
    """
    if format == "mysql":
        try:
            mydb = mysql.connector.connect(
                host=Config.host,
                user=Config.user,
                password=Config.password,
                database=Config.database
            )
            cursor = mydb.cursor()

            # 构建动态查询
            query = f"""
            SELECT timestamp, task_name, cpu_usage, cpu_power_draw, dram_usage, dram_power_draw, gpu_name, gpu_index, gpu_power_draw, utilization_gpu, utilization_memory, pcie_link_gen_current, pcie_link_width_current, temperature_gpu, temperature_memory, clocks_gr, clocks_mem, clocks_sm
            FROM {table_name}
            ORDER BY timestamp DESC;
            """
            cursor.execute(query)

            # 将查询结果加载到Pandas DataFrame中
            # 获取列名
            columns = [col[0] for col in cursor.description]
            data = cursor.fetchall()
            if not data:
                logging.warning(f"No data found in table {table_name}.")
                return
            df = pd.DataFrame(data, columns=columns)
        
        except mysql.connector.Error as err:
            logging.error(f"Database error: {err}")
            return
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            return
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'mydb' in locals():
                mydb.close()

    elif format == "csv":
        try:
            # 获取当前脚本所在目录，并构造CSV文件路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(current_dir, table_name)

            # 读取CSV数据
            df = pd.read_csv(file_path)
            if df.empty:
                logging.warning(f"No data found in file {file_path}.")
                return

        except Exception as e:
            logging.error(f"Unexpected error while reading CSV file: {e}")
            return

    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['cpu_usage'] = df['cpu_usage'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['cpu_power_draw'] = df['cpu_power_draw'].astype(str).str.replace(' W', '', regex=False).astype(float)
        df['dram_usage'] = df['dram_usage'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['dram_power_draw'] = df['dram_power_draw'].astype(str).str.replace(' W', '', regex=False).astype(float)
        df['gpu_power_draw'] = df['gpu_power_draw'].astype(str).str.replace(' W', '', regex=False).astype(float)
        df['utilization_gpu'] = df['utilization_gpu'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['utilization_memory'] = df['utilization_memory'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['temperature_gpu'] = df['temperature_gpu'].astype(str).str.replace(' °C', '', regex=False)
        df['temperature_memory'] = df['temperature_memory'].astype(str).str.replace(' °C', '', regex=False)
        df['pcie_link_gen_current'] = pd.to_numeric(df['pcie_link_gen_current'], errors='coerce')
        df['pcie_link_width_current'] = pd.to_numeric(df['pcie_link_width_current'], errors='coerce')
        df['clocks_gr'] = df['clocks_gr'].astype(str).str.replace(' MHz', '', regex=False)
        df['clocks_mem'] = df['clocks_mem'].astype(str).str.replace(' MHz', '', regex=False)
        df['clocks_sm'] = df['clocks_sm'].astype(str).str.replace(' MHz', '', regex=False)

    except Exception as e:
        logging.error(f"Error during data processing: {e}")
        return

    # 如果数据中包含gpu_index字段，则按GPU进行区分，不同GPU的数据将以不同曲线展示
    if 'gpu_index' in df.columns:
        unique_gpus = sorted(df['gpu_index'].unique())
    else:
        unique_gpus = [None]

    fig = go.Figure()
    # 针对每个GPU添加对应的曲线
    for gpu in unique_gpus:
        if gpu is not None:
            df_gpu = df[df['gpu_index'] == gpu]
            gpu_label = f"GPU {gpu}"
        else:
            df_gpu = df
            gpu_label = "GPU"
        # 展示 GPU 专属指标（功率、利用率、温度、SM 使用率）
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['gpu_power_draw'],
            mode='lines',
            name=f'{gpu_label} Power Draw (W)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['utilization_gpu'],
            mode='lines',
            name=f'{gpu_label} GPU Utilization (%)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['utilization_memory'],
            mode='lines',
            name=f'{gpu_label} Memory Utilization (%)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['temperature_gpu'],
            mode='lines',
            name=f'{gpu_label} Temperature (°C)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['temperature_memory'],
            mode='lines',
            name=f'{gpu_label} Memory Temperature (°C)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['clocks_gr'],
            mode='lines',
            name=f'{gpu_label} Graphics Clock (MHz)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['clocks_mem'],
            mode='lines',
            name=f'{gpu_label} Memory Clock (MHz)'
        ))
        fig.add_trace(go.Scatter(
            x=df_gpu['timestamp'],
            y=df_gpu['clocks_sm'],
            mode='lines',
            name=f'{gpu_label} SM Clock (MHz)'
        ))

    # 针对机器级别的数据（例如CPU使用率和PCIe相关指标），因为在每条记录中可能重复出现，所以只需添加一次
    if 'cpu_usage' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['cpu_usage'],
            mode='lines',
            name='CPU Usage (%)'
        ))
    if 'cpu_power_draw' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['cpu_power_draw'],
            mode='lines',
            name='CPU Power Draw (W)'
        ))
    if 'dram_usage' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['dram_usage'],
            mode='lines',
            name='DRAM Usage (%)'
        ))
    if 'dram_power_draw' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['dram_power_draw'],
            mode='lines',
            name='DRAM Power Draw (W)'
        ))
    if 'pcie_link_gen_current' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['pcie_link_gen_current'],
            mode='lines',
            name='PCIe Generation'
        ))
    if 'pcie_link_width_current' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['pcie_link_width_current'],
            mode='lines',
            name='PCIe Width'
        ))

    fig.update_layout(
        title=f"Interactive GPU Metrics for {table_name}",
        xaxis_title="Timestamp",
        yaxis_title="Metrics",
        legend_title="Legend",
        template="plotly_white"
    )

    output_dir = "monitor_graphs"
    output_file = os.path.join(output_dir, f"{table_name}_metrics.html")

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"Directory '{output_dir}' created.")

    try:
        fig.show()  # 显示图表
        pio.write_html(fig, file=output_file)
        logging.info(f"Chart saved as {output_file}")
    except Exception as e:
        logging.error(f"Failed to save chart: {e}")

def main():
    # 创建顶级解析器
    parser = argparse.ArgumentParser(description="Monitor stats or plot data.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-command to execute")

    # 定义监控功能的子命令
    monitor_parser = subparsers.add_parser("monitor", help="Monitor stats.")
    monitor_parser.add_argument("-n", "--name", required=True, help="Task name")
    monitor_parser.add_argument("-t", "--time_interval", type=float, default=10, help="Sampling time interval (in seconds)")
    monitor_parser.add_argument("-cmd", "--Command", required=True, help="Command to execute for the task")
    monitor_parser.add_argument("-o", "--output", choices=["mysql", "csv"], default="csv", help="Output format")

    # 定义画图功能的子命令
    plot_parser = subparsers.add_parser("plot", help="Generate plot from table.")
    plot_parser.add_argument("-t", "--table_name", required=True, help="Table name to plot")
    plot_parser.add_argument("-f", "--format", choices=["mysql", "csv"], default="csv", help="Input format")

    # 解析参数
    args = parser.parse_args()

    if args.command == "monitor":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stop_event = threading.Event()
        monitor_thread = threading.Thread(target=monitor_stats, args=(args.name, args.time_interval, timestamp, stop_event, args.output))
        monitor_thread.start()
        # 控制台输出
        print(f"ECM监控工具已启动，数据将保存至:monitor_data/{args.name}_{timestamp}.csv。")
        print(f"任务 '{args.Command}' 运行结束后，ECM监控工具将停止运行。")
        print(f"------------------------------------------------------------------------------------------")

        # 运行任务并等待其完成
        exit_code = run_task(args.Command)

        # 停止监控线程
        stop_event.set()
        monitor_thread.join()

        table_name = f"{args.name}_{timestamp}"

        # 根据任务的退出码来记录日志
        if exit_code == 0:
            logging.info(f"Task '{args.Command}' completed successfully, data was monitored and saved to table {table_name}")
            print(f"------------------------------------------------------------------------------------------")
            # print(f"任务 '{args.Command}' 运行结束，退出码: {exit_code}")
        else:
            logging.error(f"Task '{args.Command}' failed with exit code {exit_code}, data was monitored and saved to table {table_name}")
            print(f"------------------------------------------------------------------------------------------")
            # print(f"任务 '{args.Command}' 运行失败，退出码: {exit_code}")
        print(f"ECM监控工具已停止运行，共采集{inserted_count}个样本，详细数据已保存至:monitor_data/{args.name}_{timestamp}.csv，简略数据如下：")
        

        # 获取当前文件所在目录，计算指标
        current_dir = os.path.dirname(os.path.abspath(__file__))
        csv_file_path = os.path.join(current_dir, 'monitor_data', f"{args.name}_{timestamp}.csv")
        metrics = calculate_metrics(csv_file_path)
        # metrics 是 calculate_metrics 返回的结果
        cpu_dram_stats = metrics['cpu_dram_stats']
        gpu_stats = metrics['gpu_stats']
        total_time = metrics['total_time']
        energy_consumption = metrics['energy_consumption']
        print(f"任务 '{args.Command}' 耗时: {total_time}", end="")
        print(f" | CPU能耗: {energy_consumption['cpu_energy']}", end="")
        print(f" | DRAM能耗: {energy_consumption['dram_energy']}", end="")
        # 输出各个 GPU 的能耗
        for gpu in energy_consumption['gpu_energy']:
            print(f" | GPU{gpu}能耗: {energy_consumption['gpu_energy'][gpu]}", end="")
        print(" | 总能耗: ", energy_consumption['total_energy'])
        # 对应的中文键名映射
        label_map = {
            'mean': '平均值',
            'max': '最大值',
            'min': '最小值',
            'mode': '众数'
        }
        # 打印 CPU 和 DRAM 的统计信息
        print("\n【CPU/DRAM统计信息】")
        for metric, values in cpu_dram_stats.items():
            print(f"{metric}：", end="")
            details = []
            for key in ['mean', 'max', 'min', 'mode']:
                details.append(f"{label_map[key]}: {values.get(key, 'N/A')}")
            print(", ".join(details))
        # 打印各 GPU 的统计信息
        print("\n【GPU统计信息】")
        for gpu, stats in gpu_stats.items():
            print(f"GPU{gpu}：")
            for metric, values in stats.items():
                print(f"  {metric}：", end="")
                details = []
                for key in ['mean', 'max', 'min', 'mode']:
                    details.append(f"{label_map[key]}: {values.get(key, 'N/A')}")
                print(", ".join(details))
        
    elif args.command == "plot":
        # 执行画图功能
        table_name = args.table_name
        logging.info(f"Fetching data from table: {table_name}")
        fetch_and_plot_data(table_name, args.format)

if __name__ == "__main__":
    main()
    
    # # 获取平均时间
    # print(f"'get_gpu_info': Average time {get_average_time('get_gpu_info'):.4f} seconds | Max time {get_max_time('get_gpu_info'):.4f} seconds")
    # print(f"'get_sm_info': Average time {get_average_time('get_sm_info'):.4f} seconds | Max time {get_max_time('get_sm_info'):.4f} seconds")
    # print(f"'get_cpu_usage_info': Average time {get_average_time('get_cpu_usage_info'):.4f} seconds | Max time {get_max_time('get_cpu_usage_info'):.4f} seconds")
    # print(f"'get_cpu_power_info': Average time {get_average_time('get_cpu_power_info'):.4f} seconds | Max time {get_max_time('get_cpu_power_info'):.4f} seconds")
    # print(f"'get_dram_usage_info': Average time {get_average_time('get_dram_usage_info'):.4f} seconds | Max time {get_max_time('get_dram_usage_info'):.4f} seconds")
    # print(f"'get_dram_power_info': Average time {get_average_time('get_dram_power_info'):.4f} seconds | Max time {get_max_time('get_dram_power_info'):.4f} seconds")
    # print(f"'parallel_collect_metrics': Average time {get_average_time('parallel_collect_metrics'):.4f} seconds | Max time {get_max_time('parallel_collect_metrics'):.4f} seconds")
    # print(f"'save_to_csv': Average time {get_average_time('save_to_csv'):.4f} seconds | Max time {get_max_time('save_to_csv'):.4f} seconds")
    # print(f"'execution_times': Average time {get_average_time('elapsed_time'):.4f} seconds | Max time {get_max_time('elapsed_time'):.4f} seconds")