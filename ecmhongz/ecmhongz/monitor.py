import os
import csv
import subprocess
import time
import psutil
import mysql.connector
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio  # 导入io模块来保存为HTML文件
from datetime import datetime
from deprecated import deprecated
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import numpy as np
import os

# 数据库连接配置信息
class Config:
    host = "10.120.17.137"
    user = "hhz"
    password = "Bigben077"
    database = "monitor"

# 全局变量，用于记录插入的记录数
_inserted_count = -1
_monitor_running = False
_monitor_thread = None
_task_name = ""
_sampling_interval = 10
_output_format = "csv"
_timestamp = ""  
_csv_file_path = ""

# 这个函数还要重新写，对于多gpu情况需要重新计算
def calculate_metrics(file_path):
    """
    计算CSV文件中的统计信息和能耗
    参数:
    file_path (str): CSV文件路径
    返回:
    dict: 包含统计信息和能耗的字典
    """
    # 读取CSV文件
    df = pd.read_csv(file_path)
    # 将 "N/A" 替换为 NaN，不删除整行
    df.replace("N/A", np.nan, inplace=True)
    # 转换时间戳为 datetime 格式
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # 计算总时间（秒）
    total_time = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds()

    # 将百分比和单位去掉并转换为数值（遇到无法转换的保持为 NaN）
    for col in ['cpu_usage', 'cpu_power_draw', 'dram_usage', 'dram_power_draw', 
                'gpu_power_draw', 'utilization_gpu', 'utilization_memory', 
                'temperature_gpu', 'temperature_memory', 'clocks_gr', 'clocks_mem', 'clocks_sm']:
        if col in df.columns:
            # 如果列的数据类型为 object，则进行字符串替换，否则跳过
            if df[col].dtype == object:
                df[col] = df[col].str.replace(r'[^\d.]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 定义各列对应的单位（根据实际情况调整）
    unit_map = {
        'cpu_usage': ' %',
        'cpu_power_draw': ' W',
        'dram_usage': ' %',
        'dram_power_draw': ' W',
        'gpu_power_draw': ' W',
        'utilization_gpu': ' %',
        'utilization_memory': ' %',
        'temperature_gpu': ' °C',
        'temperature_memory': ' °C',
        'clocks_gr': ' MHz',
        'clocks_mem': ' MHz',
        'clocks_sm': ' MHz'
    }

    def compute_stat(series, unit):
        """计算平均、最大、最小、众数，若整列全为 NaN则返回 'N/A'"""
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

    # 计算各列的统计信息
    stats = {}
    for col in df.columns:
        if col not in ['timestamp', 'task_name', 'gpu_name', 'gpu_index']:
            unit = unit_map.get(col, '')
            stats[col] = compute_stat(df[col], unit)

    # 计算能耗：增加对全为 NaN 的判断
    df['time_interval'] = df['timestamp'].diff().dt.total_seconds().fillna(0)
    
    # CPU 能耗
    if df['cpu_power_draw'].dropna().empty:
        cpu_energy = 'N/A'
    else:
        cpu_energy_val = (df['cpu_power_draw'] * df['time_interval']).sum(skipna=True)
        cpu_energy = f"{cpu_energy_val:.2f} J"
    
    # DRAM 能耗
    if df['dram_power_draw'].dropna().empty:
        dram_energy = 'N/A'
    else:
        dram_energy_val = (df['dram_power_draw'] * df['time_interval']).sum(skipna=True)
        dram_energy = f"{dram_energy_val:.2f} J"
    
    energy_consumption = {
        'cpu_energy': cpu_energy,
        'dram_energy': dram_energy,
        'gpu_energy': {}
    }

    # 按 GPU 计算能耗（若该 GPU 组数据全为 NaN，则返回 'N/A'）
    for gpu_index in df['gpu_index'].dropna().unique():
        gpu_data = df[df['gpu_index'] == gpu_index]
        if gpu_data['gpu_power_draw'].dropna().empty:
            energy_consumption['gpu_energy'][gpu_index] = 'N/A'
        else:
            gpu_energy_val = (gpu_data['gpu_power_draw'] * gpu_data['time_interval']).sum(skipna=True)
            energy_consumption['gpu_energy'][gpu_index] = f"{gpu_energy_val:.2f} J"

    # 计算总能耗：只累加非 'N/A' 的值
    total = 0.0
    valid = False

    if cpu_energy != 'N/A':
        total += float(cpu_energy.split()[0])
        valid = True

    if dram_energy != 'N/A':
        total += float(dram_energy.split()[0])
        valid = True

    for val in energy_consumption['gpu_energy'].values():
        if val != 'N/A':
            total += float(val.split()[0])
            valid = True

    total_energy = f"{total:.2f} J" if valid else 'N/A'
    energy_consumption['total_energy'] = total_energy
    # 输出结果，总时间附带单位秒
    return {
        'stats': stats,
        'total_time': f"{total_time:.2f} 秒",
        'energy_consumption': energy_consumption
    }

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
        print(f"Error running basic command: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
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
        print(f"Error getting CPU usage info: {e}")
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
        print(f"Error getting CPU power info: {e}")
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
        print(f"Error getting DRAM usage info: {e}")
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
        print(f"Error getting DRAM power info: {e}", exc_info=True)
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
                # elif key == 'sm_info':
                #     sm_data = result
                else:
                    metrics[key] = result
            except Exception as e:
                print(f"Failed to collect metric: {key} - {str(e)}")
                metrics[key] = None
            
        metrics['gpu_info'] = gpu_data_list

    return metrics

# 存入mysql的函数太久没更新，可能有问题
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
        global _inserted_count  

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
        if _inserted_count == -1:
            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            result = cursor.fetchone()
            if result:
                print(f"Table {table_name} created")
            else:
                print(f"Failed to create table {table_name}")
            _inserted_count += 1

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
            _inserted_count += 1

        mydb.commit()
        cursor.close()
        mydb.close()

    except mysql.connector.Error as e:
        print(f"MySQL operation error: {e}")
    except Exception as e:
        print(f"Unexpected error in save_to_mysql: {e}")

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
        global _inserted_count
        global _csv_file_path

        # 生成标准化文件名
        filename = f"{task_name}_{timestamp}.csv"
        # 数据写入模式（追加模式）
        write_mode = 'a' if os.path.exists(filename) else 'w'
        # 获取该csv的路径
        _csv_file_path = os.path.abspath(filename)

        with open(filename, mode=write_mode, newline='', encoding='utf-8') as csvfile:
            # 字段顺序与MySQL表结构完全对应
            fieldnames = [
                'timestamp', 'task_name', 'cpu_usage', 'cpu_power_draw', 'dram_usage', 'dram_power_draw', 'gpu_name', 'gpu_index', 
                'gpu_power_draw', 'utilization_gpu', 'utilization_memory', 
                'pcie_link_gen_current', 'pcie_link_width_current', 
                'temperature_gpu', 'temperature_memory', 'clocks_gr', 'clocks_mem', 'clocks_sm'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # 写入表头（仅新文件需要）
            if write_mode == 'w':
                writer.writeheader()
                if _inserted_count == -1:
                    print(f"csv {filename} created")
                    _inserted_count += 1
            
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
                    'gpu_name': f"{gpu_info.get('name', 'N/A')}",
                    'gpu_index': int(gpu_info.get('index', 0)),
                    'gpu_power_draw': f"{gpu_info.get('power.draw [W]', 'N/A')}",
                    'utilization_gpu': f"{gpu_info.get('utilization.gpu [%]', 'N/A')}",
                    'utilization_memory': f"{gpu_info.get('utilization.memory [%]', 'N/A')}",
                    'pcie_link_gen_current': f"{gpu_info.get('pcie.link.gen.current', 'N/A')}",
                    'pcie_link_width_current': f"{gpu_info.get('pcie.link.width.current', 'N/A')}",

                    'temperature_gpu': f"{temp_gpu} °C" if temp_gpu != 'N/A' else "N/A",
                    'temperature_memory': f"{temp_memory} °C" if temp_memory != 'N/A' else "N/A",

                    'clocks_gr': f"{gpu_info.get('clocks.current.graphics [MHz]', 'N/A')}",
                    'clocks_mem': f"{gpu_info.get('clocks.current.memory [MHz]', 'N/A')}",
                    'clocks_sm': f"{gpu_info.get('clocks.current.sm [MHz]', 'N/A')}"
                }
                writer.writerow(row)
                _inserted_count += 1
            
    except PermissionError as pe:
        print(f"Permission denied for file {filename}: {pe}")
    except csv.Error as ce:
        print(f"CSV formatting error: {ce}")
    except Exception as e:
        print(f"Unexpected error in save_to_csv: {str(e)}")

# 根据mysql来画图的功能没完善
def draw(table_path, format):
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
            FROM {table_path}
            ORDER BY timestamp DESC;
            """
            cursor.execute(query)

            # 将查询结果加载到Pandas DataFrame中
            # 获取列名
            columns = [col[0] for col in cursor.description]
            data = cursor.fetchall()
            if not data:
                print(f"No data found in table {table_path}.")
                return
            df = pd.DataFrame(data, columns=columns)
        
        except mysql.connector.Error as err:
            print(f"Database error: {err}")
            return
        except Exception as e:
            print(f"Unexpected error: {e}")
            return
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'mydb' in locals():
                mydb.close()

    elif format == "csv":
        try:

            # 读取CSV数据
            df = pd.read_csv(table_path)
            if df.empty:
                print(f"No data found in file {table_path}.")
                return

        except Exception as e:
            print(f"Error reading CSV file: {e}")
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
        print(f"Error during data processing: {e}")
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
        title=f"Interactive GPU Metrics for {table_path}",
        xaxis_title="Timestamp",
        yaxis_title="Metrics",
        legend_title="Legend",
        template="plotly_white"
    )

    try:
        output_file = f"{table_path}_metrics.html"
        fig.show()  # 显示图表
        pio.write_html(fig, file=output_file)
        print(f"Chart saved as {output_file}")
    except Exception as e:
        print(f"Failed to save chart: {e}")

def _monitor_stats():
    """内部函数：循环采集数据直到 _monitor_running 被置为 False"""
    global _inserted_count
    while _monitor_running:
        try:
            start_time = time.time()
            # 用于数据插入的时间戳，精确到毫秒
            time_stamp_insert = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]
            # 并行采集所有指标
            metrics = parallel_collect_metrics()
            # 检查必要指标是否采集成功
            if metrics["gpu_info"] is None or metrics["cpu_usage"] is None:
                print("未能采集到部分指标，跳过本次采样。")
                time.sleep(_sampling_interval)
                continue

            # 其他指标（cpu_power, dram_power, dram_usage）
            other_metrics = [metrics["cpu_power"], metrics["dram_power"], metrics["dram_usage"]]

            # 根据输出格式调用保存函数
            if _output_format == "csv":
                save_to_csv(_task_name, metrics["cpu_usage"], metrics["gpu_info"],
                            other_metrics, _timestamp, time_stamp_insert)
            elif _output_format == "mysql":
                save_to_mysql(_task_name, metrics["cpu_usage"], metrics["gpu_info"],
                            other_metrics, _timestamp, time_stamp_insert)
            else:
                print(f"未知的输出格式：{_output_format}")
                break

            elapsed_time = time.time() - start_time
            remaining_time = max(0, _sampling_interval - elapsed_time)
            time.sleep(remaining_time)
        except Exception as e:
            print(f"监控过程中出现错误: {e}")
            time.sleep(_sampling_interval)

def start(task_name: str, sampling_interval: float = 1, output_format: str = "csv"):
    """
    启动监控：开始采集数据
    :param task_name: 任务名称，用于标识记录（同时作为保存数据的文件/表名的一部分）
    :param sampling_interval: 采样时间间隔（秒）
    :param output_format: 输出格式，支持 'csv' 或 'mysql'
    """
    global _monitor_running, _monitor_thread, _task_name, _sampling_interval, _output_format, _timestamp
    if _monitor_running:
        print(f"-----------------------------------------------------------------------------------------------------------------")
        print("ecm监控工具已经在运行。")
        print(f"-----------------------------------------------------------------------------------------------------------------")
        return
    _task_name = task_name
    _sampling_interval = sampling_interval
    _output_format = output_format.lower()
    _timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_monitor_stats, daemon=True)
    _monitor_thread.start()

    # 控制台输出
    print(f"-----------------------------------------------------------------------------------------------------------------")
    print(f"ecm监控工具已启动，正在监控任务 '{_task_name}' ,采样间隔为 {_sampling_interval} 秒，输出格式为 '{_output_format}'。")
    print(f"任务 '{_task_name}' 运行结束后，ecm监控工具将停止运行。")
    print(f"-----------------------------------------------------------------------------------------------------------------")

# 在 stop() 函数中使用：
def stop():
    global _monitor_running, _monitor_thread, _task_name, _timestamp, _inserted_count
    if not _monitor_running:
        print(f"-----------------------------------------------------------------------------------------------------------------")
        print("ecm监控工具没有在运行。")
        print(f"-----------------------------------------------------------------------------------------------------------------")
        return
    _monitor_running = False
    _monitor_thread.join()
    print(f"-----------------------------------------------------------------------------------------------------------------")
    print(f"任务 '{_task_name}' 已结束，ecm监控工具停止，共采集{_inserted_count}个样本，详细数据将保存至:{_csv_file_path}，简略数据如下：")

    metrics = calculate_metrics(_csv_file_path)
    
    stats = metrics['stats']
    total_time = metrics['total_time']
    energy_consumption = metrics['energy_consumption']
    print(f"任务 '{_task_name}' 耗时: {total_time}", end="")
    print(f" | CPU能耗: {energy_consumption['cpu_energy']}", end="")
    print(f" | DRAM能耗: {energy_consumption['dram_energy']}", end="")
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
    # 遍历 stats 字典并逐行打印
    for metric, values in stats.items():
        print(f"{metric}：", end="")
        details = []
        for key in ['mean', 'max', 'min', 'mode']:
            details.append(f"{label_map[key]}: {values.get(key, 'N/A')}")
        print(", ".join(details))
    print(f"-----------------------------------------------------------------------------------------------------------------")
