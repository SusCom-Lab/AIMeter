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

def run_task(command):
    """
    执行指定的命令并等待其完成。
    参数:
    command (str): 要执行的命令
    返回:
    int: 命令的退出码
    """
    try:
        process = subprocess.Popen(command, shell=True)
        process.wait()
        return process.returncode
    except Exception as e:
        logging.error(f"Error running task command: {e}")
        return -1

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
    # time_interval = time_interval - 1
    while not stop_event.is_set():
        try:
            start_time = time.time() # 记录开始时间
            # 用于插入数据的时间戳
            time_stamp_insert = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            gpu_info = get_gpu_info()
            if not gpu_info:
                logging.warning("No GPU info available, skipping data collection.")
                time.sleep(time_interval)
                continue

            cpu_usage = get_cpu_info()
            if cpu_usage is None:
                logging.warning("Failed to get CPU info, skipping data collection.")
                time.sleep(time_interval)
                continue
            
            cpu_power = get_cpu_power_info()
            dram_power = get_dram_power_info()
            dram_usage = get_dram_usage_info()
            other_metrics = [cpu_power, dram_power, dram_usage]

            if output_format == "csv":
                save_to_csv(task_name, cpu_usage, gpu_info, other_metrics, timestamp, time_stamp_insert)
            elif output_format == "mysql":
                save_to_mysql(task_name, cpu_usage, gpu_info, other_metrics, timestamp, time_stamp_insert)

            if inserted_count % 10 == 0 or inserted_count == 1:
                logging.info(f"Total records inserted so far: {inserted_count}")

            # time.sleep(time_interval)
            elapsed_time = time.time() - start_time
            remaining_time = max(0, time_interval - elapsed_time)
            time.sleep(remaining_time)

        except Exception as e:
            logging.error(f"Unexpected error in monitor_stats: {e}")
            time.sleep(time_interval)       

def get_gpu_info():
    """
    获取GPU信息
    返回:
    list: 包含GPU信息的字典列表
    """
    command = [
        "nvidia-smi --query-gpu=name,index,power.draw,utilization.gpu,utilization.memory,pcie.link.gen.current,pcie.link.width.current,temperature.gpu,temperature.memory,clocks.gr,clocks.mem  --format=csv"
    ]
    try:
        result = subprocess.check_output(command, shell=True).decode('utf-8')
        lines = result.strip().split("\n")
        headers = lines[0].split(", ")
        gpu_data_list = []
        line_num = 1
        while line_num < len(lines) and lines[line_num].strip():
            gpu_data = {}
            values = lines[line_num].split(", ")
            for i, header in enumerate(headers):
                gpu_data[header] = values[i]
            gpu_data_list.append(gpu_data)
            line_num += 1
        
        # 构建用于获取包含sm信息的命令
        command_sm_info = ["nvidia-smi dmon -s u -c 1"]  # -s u表示按更新频率排序，-c 1表示只获取1次数据更新
        result_sm_info = subprocess.check_output(command_sm_info, shell=True).decode('utf-8')
        lines_sm_info = result_sm_info.strip().split("\n")

        # 找到包含'sm'字段的标题行
        header_line_sm_info = None
        for line in lines_sm_info:
            if line.startswith("# gpu") and "sm" in line:
                header_line_sm_info = line
                break
        
        if header_line_sm_info:
            headers_sm_info = header_line_sm_info.split()
            sm_index = None
            for index, header in enumerate(headers_sm_info):
                if header == "sm":
                    sm_index = index - 1  # 由于标题行以'#'开头，因此实际数据行的索引要减1
                    break
            # 从数据行中提取'sm'对应的值添加到之前获取的gpu_data字典中，适配不同数量的GPU
            data_line_num = 0
            while data_line_num < len(lines_sm_info) and lines_sm_info[data_line_num].strip():
                values_sm_info = lines_sm_info[data_line_num].split()
                # 添加判断条件，跳过以'#'开头的数据行
                if values_sm_info[0].startswith('#'):
                    data_line_num += 1
                    continue
                gpu_index = int(values_sm_info[0])
                if gpu_index < len(gpu_data_list):
                    gpu_data_list[gpu_index]["sm"] = values_sm_info[sm_index]
                data_line_num += 1
        return gpu_data_list

    except subprocess.CalledProcessError as e:
        logging.error(f"Error getting GPU info: {e}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error in get_gpu_info: {e}")
        return []

def get_cpu_info():
    """
    获取CPU信息
    返回:
    float: CPU使用率
    """
    try:
        cpu_usage = psutil.cpu_percent(interval=0.25)
        return cpu_usage
    except Exception as e:
        logging.error(f"Error getting CPU info: {e}")
        return None
    
def get_cpu_power_info(sample_interval=0.1):
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

def get_dram_power_info(sample_interval=0.1):
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
            sm VARCHAR(50) COMMENT 'SM (Streaming Multiprocessor) utilization or status',
            clocks_gr VARCHAR(50) COMMENT 'Graphics clock frequency',
            clocks_mem VARCHAR(50) COMMENT 'Memory clock frequency'
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
                                pcie_link_gen_current, pcie_link_width_current, temperature_gpu, temperature_memory, sm, clocks_gr, clocks_mem)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for gpu_info in gpu_data_list:
            
            #  GPU温度可能不可用
            temp_gpu = gpu_info.get("temperature.gpu", "N/A")
            temp_memory = gpu_info.get("temperature.memory", "N/A")
            sm_val = gpu_info.get("sm", "N/A")

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
                f"{sm_val} %" if sm_val != "N/A" else "N/A",

                f"{gpu_info.get('clocks.current.graphics [MHz]', '')}",
                f"{gpu_info.get('clocks.current.memory [MHz]', '')}"
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

        # 生成标准化文件名
        filename = f"{task_name}_{timestamp}.csv"
        
        # 数据写入模式（追加模式）
        write_mode = 'a' if os.path.exists(filename) else 'w'

        with open(filename, mode=write_mode, newline='', encoding='utf-8') as csvfile:
            # 字段顺序与MySQL表结构完全对应
            fieldnames = [
                'timestamp', 'task_name', 'cpu_usage', 'cpu_power_draw', 'dram_usage', 'dram_power_draw', 'gpu_name', 'gpu_index', 
                'gpu_power_draw', 'utilization_gpu', 'utilization_memory', 
                'pcie_link_gen_current', 'pcie_link_width_current', 
                'temperature_gpu', 'temperature_memory', 'sm', 'clocks_gr', 'clocks_mem'
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
                sm_val = gpu_info.get('sm', 'N/A')
                
                row = {
                    'timestamp': time_stamp_insert,
                    'task_name': task_name,
                    'cpu_usage': f"{cpu_usage:.2f} %",
                    'cpu_power_draw': f"{other_metrics[0]:.2f} W",
                    'dram_power_draw': f"{other_metrics[1]:.2f} W",
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
                    'sm': f"{sm_val} %" if sm_val != 'N/A' else "N/A",

                    'clocks_gr': f"{gpu_info.get('clocks.current.graphics [MHz]', 'N/A')}",
                    'clocks_mem': f"{gpu_info.get('clocks.current.memory [MHz]', 'N/A')}"
                }
                writer.writerow(row)
                inserted_count += 1
            
    except PermissionError as pe:
        logging.error(f"Permission denied for file {filename}: {pe}")
    except csv.Error as ce:
        logging.error(f"CSV formatting error: {ce}")
    except Exception as e:
        logging.error(f"Unexpected error in save_to_csv: {str(e)}")

@deprecated(version='1.0', reason="只能处理单个GPU的数据，不适用于多GPU的情况")
def fetch_and_plot_data(table_name, format):
    """
    从MySQL数据库或csv文件中检索数据并绘制图表
    参数:
    table_name (str): 数据表名称
    format (str): 输入格式（mysql或csv）
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
            SELECT timestamp, power_draw, utilization_gpu, utilization_memory, temperature_gpu, temperature_memory, cpu_usage, sm, pcie_link_gen_current, pcie_link_width_current
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
            # 获取当前脚本所在的目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 构建文件路径（与当前文件同级目录）
            file_path = os.path.join(current_dir, table_name)

            # 从CSV文件读取数据
            df = pd.read_csv(file_path)
            if df.empty:
                logging.warning(f"No data found in file {file_path}.")
                return

        except Exception as e:
            logging.error(f"Unexpected error while reading CSV file: {e}")
            return
    
    # 数据预处理
    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['power_draw'] = df['power_draw'].astype(str).str.replace(' W', '', regex=False).astype(float)
        df['utilization_gpu'] = df['utilization_gpu'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['utilization_memory'] = df['utilization_memory'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['temperature_gpu'] = df['temperature_gpu'].astype(str).str.replace(' °C', '', regex=False).astype(float)
        df['temperature_memory'] = df['temperature_memory'].astype(str).str.replace(' °C', '', regex=False).astype(float)
        df['cpu_usage'] = df['cpu_usage'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['sm'] = df['sm'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['pcie_generation'] = pd.to_numeric(df['pcie_link_gen_current'], errors='coerce')
        df['pcie_width'] = pd.to_numeric(df['pcie_link_width_current'], errors='coerce')
    except Exception as e:
        logging.error(f"Error during data processing: {e}")
        return

    # 创建图表
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['power_draw'], mode='lines', name='GPU Power Draw (W)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['utilization_gpu'], mode='lines', name='GPU Utilization (%)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['utilization_memory'], mode='lines', name='GPU Memory Utilization (%)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['temperature_gpu'], mode='lines', name='GPU Temperature (°C)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['temperature_memory'], mode='lines', name='GPU Memory Temperature (°C)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['cpu_usage'], mode='lines', name='CPU Usage (%)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['sm'], mode='lines', name='GPU SM (%)'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['pcie_generation'], mode='lines', name='GPU PCIe Generation'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['pcie_width'], mode='lines', name='GPU PCIe Width'))

    # 设置图表标题和轴标签
    fig.update_layout(
        title=f"Interactive GPU Metrics for {table_name}",
        xaxis_title="Timestamp",
        yaxis_title="Metrics",
        legend_title="Legend",
        template="plotly_white"
    )

    # 保存图表为HTML文件
    output_dir = "monitor_graphs"
    output_file = os.path.join(output_dir, f"{table_name}_metrics.html")

    # 确保目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"Directory '{output_dir}' created.")

    try:
        fig.show()  # 直接显示图表
        pio.write_html(fig, file=output_file)
        logging.info(f"Chart saved as {output_file}")
    except Exception as e:
        logging.error(f"Failed to save chart: {e}")

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
            SELECT timestamp, task_name, cpu_usage, cpu_power_draw, dram_usage, dram_power_draw, gpu_name, gpu_index, gpu_power_draw, utilization_gpu, utilization_memory, pcie_link_gen_current, pcie_link_width_current, temperature_gpu, temperature_memory, sm, clocks_gr, clocks_mem
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
        df['gpu_power_draw'] = df['power_draw'].astype(str).str.replace(' W', '', regex=False).astype(float)
        df['utilization_gpu'] = df['utilization_gpu'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['utilization_memory'] = df['utilization_memory'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['temperature_gpu'] = df['temperature_gpu'].astype(str).str.replace(' °C', '', regex=False)
        df['temperature_memory'] = df['temperature_memory'].astype(str).str.replace(' °C', '', regex=False)
        df['sm'] = df['sm'].astype(str).str.replace(' %', '', regex=False).astype(float)
        df['pcie_link_gen_current'] = pd.to_numeric(df['pcie_link_gen_current'], errors='coerce')
        df['pcie_link_width_current'] = pd.to_numeric(df['pcie_link_width_current'], errors='coerce')
        df['clocks_gr'] = pd.to_numeric(df['clocks_gr'], errors='coerce')
        df['clocks_mem'] = pd.to_numeric(df['clocks_mem'], errors='coerce')

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
            y=df_gpu['sm'],
            mode='lines',
            name=f'{gpu_label} SM (%)'
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
    monitor_parser.add_argument("-t", "--time_interval", type=int, default=10, help="Sampling time interval (in seconds)")
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
        
        # 运行任务并等待其完成
        exit_code = run_task(args.Command)

        # 停止监控线程
        stop_event.set()
        monitor_thread.join()

        table_name = f"{args.name}_{timestamp}"

        # 根据任务的退出码来记录日志
        if exit_code == 0:
            logging.info(f"Task '{args.Command}' completed successfully, data was monitored and saved to table {table_name}")
        else:
            logging.error(f"Task '{args.Command}' failed with exit code {exit_code}, data was monitored and saved to table {table_name}")
    
    elif args.command == "plot":
        # 执行画图功能
        table_name = args.table_name
        logging.info(f"Fetching data from table: {table_name}")
        fetch_and_plot_data(table_name, args.format)

if __name__ == "__main__":
    main()