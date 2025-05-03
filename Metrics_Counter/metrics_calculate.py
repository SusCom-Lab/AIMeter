import pandas as pd
import numpy as np
from config import Config
import pandas as pd
import numpy as np
import mysql.connector
import re
from save import sanitize_metric_key

def calculate_metrics(file_path: str) -> dict[str, any]:
    """
    计算CSV文件中的统计信息和能耗。
    使用 'index' 列按 GPU 分组，并处理由 save_to_csv 生成的列名和格式。
    参数:
        file_path (str): CSV文件路径
    返回:
        dict: 包含CPU/DRAM统计信息、各GPU统计信息、总时间和能耗的字典
              如果文件无法读取或处理，可能返回空字典或引发异常。
    """
    try:
        df = pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"错误：文件未找到于 {file_path}")
        return {}
    except Exception as e:
        print(f"错误：读取CSV文件 {file_path} 时出错: {e}")
        return {}
    
    if df.empty:
        print(f"警告：CSV文件 {file_path} 为空。")
        return {}
    # 将 "N/A" 和空字符串替换为 NaN
    df.replace(["N/A", ""], np.nan, inplace=True)
    # 转换时间戳
    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        # 按时间戳排序，确保时间顺序正确
        df.sort_values('timestamp', inplace=True)
        # 计算总时间
        total_time = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds() if len(df['timestamp']) > 1 else 0
    except KeyError:
        print("错误：未找到 'timestamp' 列。")
        return {}
    except Exception as e:
        print(f"错误：处理 'timestamp' 时出错: {e}")
        return {}

    # --- 列名和单位定义 (基于 save_to_csv 输出) ---
    # 列需要清理单位 (%, W, °C, MHz 等) 以进行数值计算
    # save_to_csv 写入的列名直接来自 metrics 字典的键

    # cols_to_clean: 包含所有需要从中移除单位 (%, W, °C, MHz, B/s 等) 以进行数值计算的列
    cols_to_clean = [
        # --- CPU 指标 ---
        'cpu_usage',      # 示例: '5.9 %'
        'cpu_power',      # 示例: 'N/A' (仍然包含，以防后续出现 ' W')
        # --- DRAM 指标 ---
        'dram_usage',     # 示例: '24.0 %'
        'dram_power',     # 示例: 'N/A' (仍然包含，以防后续出现 ' W')
        # --- GPU 指标 (来自您数据的通用和特定指标) ---
        'utilization.gpu [%]', # 示例: '71 %'
        'power.draw [W]',   # 示例: '292.65 W'
        'temperature.gpu',  # 示例: '79 °C'
        'temperature.memory',# 示例: '85 °C'
        'utilization.memory [%]', # 示例: '55 %'
        'clocks.current.graphics [MHz]', # 示例: '1125 MHz'
        'clocks.current.memory [MHz]', # 示例: '1512 MHz'
        'clocks.current.sm [MHz]',  # 示例: '1125 MHz'
        # --- GPU 指标 (FPx 活动状态) ---
        'fp64_active',      # 示例: '0.00 %'
        'fp32_active',      # 示例: '0.00 %'
        'fp16_active',      # 示例: '0.00 %'
        # --- GPU 指标 (DCGM 及其他) ---
        'pcie_tx_bytes',    # 示例: '0.21 GB/s'
        'pcie_rx_bytes',    # 示例: '0.09 GB/s'
        'tensor_active',    # 示例: '0.40 %'
        'sm_active',        # 示例: '100.00 %'
        'sm_occupancy',     # 示例: '99.10 %'
        'nvlink_tx_bytes',  # 示例: '0 GB/s'
        'nvlink_rx_bytes',  # 示例: '0 GB/s'
        'dram_active',      # 示例: '52.30 %'
        'usage.memory [%]', # 示例: '85 %'
        # --- 不需要清理的列 (纯数值) ---
        # 'pcie.link.gen.current', # 示例: 4
        # 'pcie.link.width.current', # 示例: 16
    ]

    # unit_map: 包含所有计算了统计信息后，需要在结果中显示单位的列及其单位字符串
    unit_map = {
        # --- CPU ---
        'cpu_usage': ' %',
        'cpu_power': ' W',
        # --- DRAM ---
        'dram_usage': ' %',
        'dram_power': ' W',
        # --- GPU 通用和特定指标 ---
        'utilization.gpu [%]': ' %',
        'power.draw [W]': ' W',
        'temperature.gpu': ' °C',
        'temperature.memory': ' °C',
        'utilization.memory [%]': ' %',
        'clocks.current.graphics [MHz]': ' MHz',
        'clocks.current.memory [MHz]': ' MHz',
        'clocks.current.sm [MHz]': ' MHz',
        # --- GPU FPx ---
        'fp64_active': ' %',
        'fp32_active': ' %',
        'fp16_active': ' %',
        # --- GPU DCGM 及其他 ---
        'pcie_tx_bytes': ' GB/s',
        'pcie_rx_bytes': ' GB/s',
        'tensor_active': ' %',
        'sm_active': ' %',
        'sm_occupancy': ' %',
        'nvlink_tx_bytes': ' GB/s',
        'nvlink_rx_bytes': ' GB/s',
        'dram_active': ' %',
        'usage.memory [%]': ' %',
        # --- 没有单位的列 (或输出统计信息中不需要单位的列) ---
        'pcie.link.gen.current': '', # 链路代数不需要单位后缀
        'pcie.link.width.current': '', # 链路宽度不需要单位后缀
    }

    # --- 清洗数据 ---
    for col in cols_to_clean:
        if col in df.columns:
            if df[col].dtype == object:
                # 移除所有非数字和小数点的字符
                df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
            # 转换为数值，无法转换的变为 NaN
            df[col] = pd.to_numeric(df[col], errors='coerce')
        # else:
            # print(f"信息：在CSV中未找到用于清理的列 '{col}'。") # 可选信息消息

    # --- 统计计算函数 ---
    def compute_stat(series, unit):
        """计算平均、最大、最小、众数；若整列全为NaN则返回 'N/A'"""
        series_clean = series.dropna()
        if series_clean.empty:
            return {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'}
        else:
            try:
                mean_val = f"{series_clean.mean():.2f}{unit}"
                max_val = f"{series_clean.max():.2f}{unit}"
                min_val = f"{series_clean.min():.2f}{unit}"
                mode_series = series_clean.mode()
                # 处理众数可能返回多个值或为空的情况 (尽管在 dropna 后不太可能)
                mode_val = f"{mode_series.iloc[0]:.2f}{unit}" if not mode_series.empty else "N/A"
            except Exception as e:
                print(f"错误：计算序列统计信息时出错: {e}")
                return {'mean': 'Error', 'max': 'Error', 'min': 'Error', 'mode': 'Error'}
            return {'mean': mean_val, 'max': max_val, 'min': min_val, 'mode': mode_val}

    # --- 计算 CPU 和 DRAM 统计指标 ---
    cpu_dram_columns = ['cpu_usage', 'cpu_power', 'dram_usage', 'dram_power']
    cpu_dram_stats = {}
    for col in cpu_dram_columns:
        if col in df.columns:
            unit = unit_map.get(col, '') # 获取单位，默认为空字符串
            cpu_dram_stats[col] = compute_stat(df[col], unit)
        else:
            cpu_dram_stats[col] = {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'} # 如果列缺失则标记为 N/A


    # --- 计算 GPU 相关统计指标 (按 'index' 分组) ---
    # 动态识别 GPU 相关列（不包括 CPU/DRAM 或固定 ID 列）
    fixed_cols = ['timestamp', 'task_name', 'name', 'index']
    gpu_metric_columns = [col for col in df.columns if col not in cpu_dram_columns and col not in fixed_cols]
    # 筛选出 GPU 相关列，确保它们在 unit_map 中有单位或是数值类型
    gpu_cols_to_stat = [col for col in gpu_metric_columns if col in unit_map or pd.api.types.is_numeric_dtype(df[col])]

    gpu_stats = {}
    if 'index' in df.columns:
        # 转换 'index' 列为字符串类型以便分组
        df['index'] = df['index'].astype(str)
        # 在分组之前排除 index 为 NaN 的行
        grouped_gpus = df.dropna(subset=['index']).groupby('index')

        for gpu_idx, group in grouped_gpus:
            if gpu_idx == 'nan': # Skip groups formed by NaN indices 中文：跳过
                continue
            gpu_stats[gpu_idx] = {}
             # 每个组添加一次 GPU 名称 (使用找到的第一个非空名称)
            gpu_stats[gpu_idx]['name'] = group['name'].dropna().iloc[0] if 'name' in group.columns and not group['name'].dropna().empty else 'N/A'

            for col in gpu_cols_to_stat:
                if col in group.columns:
                    unit = unit_map.get(col, '') # 获取单位
                    gpu_stats[gpu_idx][col] = compute_stat(group[col], unit)
                # else: # 列可能存在于 df 中，但不在这个特定组中 (使用 groupby 时不太可能)
                #     gpu_stats[gpu_idx][col] = {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'}
    else:
        print("警告：未找到用于 GPU 分组的 'index' 列。")

    # --- 能耗计算 ---
    energy_consumption = {
        'cpu_energy': 'N/A',
        'dram_energy': 'N/A',
        'gpu_energy': {},
        'total_energy': 'N/A'
    }
    total_energy_joules = 0.0
    energy_calculation_possible = False

    # CPU/DRAM Energy: Use data potentially duplicated across GPUs per timestamp
    # 需要首先选择唯一时间戳以进行正确的间隔计算
    # 确保功率列存在且为数值类型 *在* 计算之前
    if 'timestamp' in df.columns:
        df_unique_time = df.drop_duplicates(subset=['timestamp']).copy()
        df_unique_time['time_interval'] = df_unique_time['timestamp'].diff().dt.total_seconds()
        # 第一个间隔是 NaN，将此未知间隔期间的功率视为 0 贡献还是进行估算？
        # 我们将间隔的 fillna(0)，意味着第一个测量点不增加能量持续时间。
        df_unique_time['time_interval'] = df_unique_time['time_interval'].fillna(0)

        # 检查并计算 CPU 能耗
        cpu_power_col = 'cpu_power'
        if cpu_power_col in df_unique_time.columns and pd.api.types.is_numeric_dtype(df_unique_time[cpu_power_col]):
            # 确保没有负的时间间隔 (可能发生在未排序的数据中，尽管我们已排序)
            df_unique_time['time_interval'] = df_unique_time['time_interval'].clip(lower=0)
            # 计算能耗，跳过功率消耗中的 NaN
            cpu_energy_joules = (df_unique_time[cpu_power_col].fillna(0) * df_unique_time['time_interval']).sum()
            energy_consumption['cpu_energy'] = f"{cpu_energy_joules:.2f} J"
            total_energy_joules += cpu_energy_joules
            energy_calculation_possible = True
        else:
            # print(f"信息：无法计算 CPU 能耗。列 '{cpu_power_col}' 缺失或非数值类型。")
            pass

        # 检查并计算 DRAM 能耗
        dram_power_col = 'dram_power'
        if dram_power_col in df_unique_time.columns and pd.api.types.is_numeric_dtype(df_unique_time[dram_power_col]):
            df_unique_time['time_interval'] = df_unique_time['time_interval'].clip(lower=0)
            dram_energy_joules = (df_unique_time[dram_power_col].fillna(0) * df_unique_time['time_interval']).sum()
            energy_consumption['dram_energy'] = f"{dram_energy_joules:.2f} J"
            total_energy_joules += dram_energy_joules
            energy_calculation_possible = True
        else:
            # print(f"信息：无法计算 DRAM 能耗。列 '{dram_power_col}' 缺失或非数值类型。")
            pass

    # GPU Energy: Calculate per GPU using grouped data
    gpu_power_col = 'power.draw [W]' # 确保这与实际的列名匹配
    if 'index' in df.columns and gpu_power_col in df.columns:
        # 使用与统计计算相同的 grouped_gpus
        for gpu_idx, group in grouped_gpus:
              if gpu_idx == 'nan': continue # 跳过 NaN 索引组
              # 为保险起见按时间对组进行排序，在组内计算间隔
              group_sorted = group.sort_values('timestamp').copy()
              group_sorted['time_interval'] = group_sorted['timestamp'].diff().dt.total_seconds().fillna(0).clip(lower=0)

              if pd.api.types.is_numeric_dtype(group_sorted[gpu_power_col]):
                  gpu_energy_joules = (group_sorted[gpu_power_col].fillna(0) * group_sorted['time_interval']).sum()
                  energy_consumption['gpu_energy'][gpu_idx] = f"{gpu_energy_joules:.2f} J"
                  total_energy_joules += gpu_energy_joules
                  energy_calculation_possible = True
              else:
                  energy_consumption['gpu_energy'][gpu_idx] = 'N/A'
                  print(f"信息：无法计算 GPU {gpu_idx} 的能耗。列 '{gpu_power_col}' 在其组内缺失或非数值类型。")

    if energy_calculation_possible:
        energy_consumption['total_energy'] = f"{total_energy_joules:.2f} J"

    # --- 返回结果 ---
    return {
        'cpu_dram_stats': cpu_dram_stats,
        'gpu_stats': gpu_stats,
        'total_time': f"{total_time:.2f} 秒",
        'energy_consumption': energy_consumption
    }

def calculate_metrics_from_mysql(table_name: str) -> dict[str, any]:
    """
    从指定的 MySQL 表读取数据，计算统计信息和能耗。
    处理动态创建的、名称经过 sanitize 的列，并返回包含原始 metric 键的字典。
    参数:
        table_name (str): 要读取数据的确切 MySQL 表名。
    返回:
        dict: 包含统计信息和能耗的字典，使用 *原始* metric 名称作为键。
              如果出错则返回空字典。
    """
    # --- 1. 连接并读取数据 ---
    mydb = None
    df = None

    # print(f"尝试从 MySQL 表计算指标: `{table_name}`")

    try:
        mydb = mysql.connector.connect(
            host=Config.host, 
            user=Config.user,
            password=Config.password, 
            database=Config.database
        )
        # 使用提供的表名获取所有数据
        query = f"SELECT * FROM `{table_name}` ORDER BY timestamp" # 如果表名包含特殊字符，反引号很重要
        df = pd.read_sql(query, mydb)

    except mysql.connector.Error as e:
        if e.errno == 1146: # ER_NO_SUCH_TABLE
             print(f"错误：未找到 MySQL 表 `{table_name}`。")
        else:
             print(f"从 `{table_name}` 获取数据时 MySQL 错误: {e}")
        return {}
    except Exception as e:
        # 捕获 pandas 无法读取 SQL 表时的潜在错误
        print(f"从 MySQL 表 `{table_name}` 读取数据到 DataFrame 时出错: {e}")
        return {}
    finally:
        if mydb and mydb.is_connected():
            mydb.close()

    if df.empty:
        print(f"警告：在 MySQL 表 `{table_name}` 中未找到数据。")
        return {}

    # --- 2. 初始数据准备 ---
    df.replace(["N/A", ""], np.nan, inplace=True)
    df.fillna(value=np.nan, inplace=True) # 确保数据库的 NULL 值是 NaN

    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.sort_values('timestamp', inplace=True)
        total_time = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds() if len(df['timestamp']) > 1 else 0
    except KeyError:
        print("错误：在获取的 MySQL 数据中未找到 'timestamp' 列。")
        return {}
    except Exception as e:
        print(f"处理来自 MySQL 数据的 'timestamp' 时出错: {e}")
        return {}

    # --- 3. 定义映射 (原始 -> 清理后, 清理后 -> 单位, 清理后 -> 原始) ---
    original_unit_map = {
        'cpu_usage': ' %', 
        'cpu_power': ' W', 
        'dram_usage': ' %', 
        'dram_power': ' W',
        'utilization.gpu [%]': ' %', 
        'power.draw [W]': ' W', 
        'temperature.gpu': ' °C',
        'temperature.memory': ' °C', 
        'utilization.memory [%]': ' %',
        'clocks.current.graphics [MHz]': ' MHz', 
        'clocks.current.memory [MHz]': ' MHz',
        'clocks.current.sm [MHz]': ' MHz', 
        'fp64_active': ' %', 
        'fp32_active': ' %',
        'fp16_active': ' %', 
        'pcie_tx_bytes': ' GB/s', 
        'pcie_rx_bytes': ' GB/s',
        'tensor_active': ' %', 
        'sm_active': ' %', 
        'sm_occupancy': ' %',
        'nvlink_tx_bytes': ' GB/s', 
        'nvlink_rx_bytes': ' GB/s', 
        'dram_active': ' %',
        'usage.memory [%]': ' %', 
        'pcie.link.gen.current': '', 
        'pcie.link.width.current': '',
        'name': '', 
        'index': '', # 添加映射所需的非单位键
    }

    def compute_stat(series, unit):
        """计算平均、最大、最小、众数；若整列全为NaN则返回 'N/A'"""
        series_clean = series.dropna()
        if series_clean.empty:
            return {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'}
        else:
            try:
                mean_val = f"{series_clean.mean():.2f}{unit}"
                max_val = f"{series_clean.max():.2f}{unit}"
                min_val = f"{series_clean.min():.2f}{unit}"
                mode_series = series_clean.mode()
                # 处理众数可能返回多个值或为空的情况 (尽管在 dropna 后不太可能)
                mode_val = f"{mode_series.iloc[0]:.2f}{unit}" if not mode_series.empty else "N/A"
            except Exception as e:
                # 保持英文错误消息，因为这是程序输出，可能用于日志分析
                print(f"Error calculating stats for series: {e}")
                return {'mean': 'Error', 'max': 'Error', 'min': 'Error', 'mode': 'Error'}
            return {'mean': mean_val, 'max': max_val, 'min': min_val, 'mode': mode_val}
    
    original_cols_to_clean = [k for k, v in original_unit_map.items() if v.strip()]

    sanitized_unit_map = {sanitize_metric_key(k): v for k, v in original_unit_map.items()}
    sanitized_cols_to_clean = {sanitize_metric_key(k) for k in original_cols_to_clean}
    # 确保反向映射包含原始映射中的所有键
    reverse_name_map = {sanitize_metric_key(k): k for k in original_unit_map.keys()}

    # --- 4. 清理数据 (使用清理后的名称) ---
    for col in sanitized_cols_to_clean:
        if col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # --- 新增：显式转换已知应为数值但未被清洗的列 ---
    known_numeric_sanitized = {
        sanitize_metric_key('pcie.link.gen.current'),
        sanitize_metric_key('pcie.link.width.current')
        # 如果还有其他类似的列，也添加到这里
    }
    for col in known_numeric_sanitized:
        if col in df.columns:
            # 尝试将列转换为数值，无法转换的（如 '444444'）将变为 NaN
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # --- 5. 计算 CPU/DRAM 统计信息 (使用清理后的名称) ---
    sanitized_cpu_dram_cols = {sanitize_metric_key(k) for k in ['cpu_usage', 'cpu_power', 'dram_usage', 'dram_power']}
    cpu_dram_stats_sanitized = {}
    df_unique_time = df.drop_duplicates(subset=['timestamp']).copy()

    for col in sanitized_cpu_dram_cols:
        if col in df_unique_time.columns:
            unit = sanitized_unit_map.get(col, '')
            cpu_dram_stats_sanitized[col] = compute_stat(df_unique_time[col], unit)
        else:
            cpu_dram_stats_sanitized[col] = {'mean': 'N/A', 'max': 'N/A', 'min': 'N/A', 'mode': 'N/A'}

    # --- 6. 计算 GPU 统计信息 (使用清理后的名称) ---
    gpu_stats_sanitized = {}
    sanitized_gpu_index_col = sanitize_metric_key('index')
    sanitized_gpu_name_col = sanitize_metric_key('name')

    # 识别 DataFrame 中存在的潜在 GPU 列
    potential_gpu_metric_cols = {
        col for col in df.columns
        if col not in sanitized_cpu_dram_cols and col not in ['id', 'timestamp', 'task_name', sanitized_gpu_index_col, sanitized_gpu_name_col]
    }

    if sanitized_gpu_index_col in df.columns:
        try:
            # 尝试转换为数值进行排序，处理错误，然后转换为字符串进行分组
            numeric_index = pd.to_numeric(df[sanitized_gpu_index_col], errors='coerce')
            df_sorted_index = df.iloc[numeric_index.argsort()].copy()
            df_sorted_index[sanitized_gpu_index_col] = df_sorted_index[sanitized_gpu_index_col].astype(str)
        except Exception:
             print("警告：无法按数值 GPU 索引排序，使用字符串。")
             df_sorted_index = df.copy()
             df_sorted_index[sanitized_gpu_index_col] = df_sorted_index[sanitized_gpu_index_col].astype(str)

        grouped_gpus = df_sorted_index.dropna(subset=[sanitized_gpu_index_col]).groupby(sanitized_gpu_index_col)

        for gpu_idx, group in grouped_gpus:
            if gpu_idx.lower() == 'nan': continue

            gpu_stats_sanitized[gpu_idx] = {}
            # GPU 名称
            if sanitized_gpu_name_col in group.columns:
                 name_series = group[sanitized_gpu_name_col].dropna()
                 gpu_stats_sanitized[gpu_idx][sanitized_gpu_name_col] = name_series.iloc[0] if not name_series.empty else 'N/A'
            else:
                 gpu_stats_sanitized[gpu_idx][sanitized_gpu_name_col] = 'N/A'

            # 计算在此组中找到的其他 GPU 列的统计信息
            for col in potential_gpu_metric_cols:
                if col in group.columns: # 检查该列是否存在于此特定组中
                    unit = sanitized_unit_map.get(col, '') # 根据清理后的名称查找单位
                    gpu_stats_sanitized[gpu_idx][col] = compute_stat(group[col], unit)

    else:
        print(f"警告：未找到用于 GPU 分组的清理后索引列 '{sanitized_gpu_index_col}'。")

    # --- 7. 计算能耗 (使用清理后的名称) ---
    energy_consumption = {'cpu_energy': 'N/A', 'dram_energy': 'N/A', 'gpu_energy': {}, 'total_energy': 'N/A'}
    total_energy_joules = 0.0
    energy_calculation_possible = False

    s_cpu_power = sanitize_metric_key('cpu_power')
    s_dram_power = sanitize_metric_key('dram_power')
    s_gpu_power = sanitize_metric_key('power.draw [W]')

    df_unique_time['time_interval'] = df_unique_time['timestamp'].diff().dt.total_seconds().fillna(0).clip(lower=0)

    # CPU 能耗
    if s_cpu_power in df_unique_time.columns and pd.api.types.is_numeric_dtype(df_unique_time[s_cpu_power]):
        cpu_energy_joules = (df_unique_time[s_cpu_power].fillna(0) * df_unique_time['time_interval']).sum()
        energy_consumption['cpu_energy'] = f"{cpu_energy_joules:.2f} J"
        total_energy_joules += cpu_energy_joules
        energy_calculation_possible = True
    # else: print(f"信息：无法计算 CPU 能耗...") # 减少冗余信息

    # DRAM 能耗
    if s_dram_power in df_unique_time.columns and pd.api.types.is_numeric_dtype(df_unique_time[s_dram_power]):
        dram_energy_joules = (df_unique_time[s_dram_power].fillna(0) * df_unique_time['time_interval']).sum()
        energy_consumption['dram_energy'] = f"{dram_energy_joules:.2f} J"
        total_energy_joules += dram_energy_joules
        energy_calculation_possible = True
    # else: print(f"信息：无法计算 DRAM 能耗...")

    # GPU 能耗
    if sanitized_gpu_index_col in df.columns and s_gpu_power in df.columns:
        if 'grouped_gpus' not in locals(): # 如果之前的分组失败或统计不需要分组，则重新分组
             df[sanitized_gpu_index_col] = df[sanitized_gpu_index_col].astype(str)
             grouped_gpus = df.dropna(subset=[sanitized_gpu_index_col]).groupby(sanitized_gpu_index_col)

        for gpu_idx, group in grouped_gpus:
            if gpu_idx.lower() == 'nan': continue
            group_sorted = group.sort_values('timestamp').copy()
            group_sorted['time_interval'] = group_sorted['timestamp'].diff().dt.total_seconds().fillna(0).clip(lower=0)

            if s_gpu_power in group_sorted.columns and pd.api.types.is_numeric_dtype(group_sorted[s_gpu_power]):
                gpu_energy_joules = (group_sorted[s_gpu_power].fillna(0) * group_sorted['time_interval']).sum()
                energy_consumption['gpu_energy'][gpu_idx] = f"{gpu_energy_joules:.2f} J"
                total_energy_joules += gpu_energy_joules
                energy_calculation_possible = True
            else:
                energy_consumption['gpu_energy'][gpu_idx] = 'N/A'

    if energy_calculation_possible:
        energy_consumption['total_energy'] = f"{total_energy_joules:.2f} J"

    # --- 8. 映射键名并返回 ---
    final_result = {}
    final_result['total_time'] = f"{total_time:.2f} 秒"
    final_result['energy_consumption'] = energy_consumption

    # 使用反向映射将 CPU/DRAM 统计信息的键映射回去
    final_result['cpu_dram_stats'] = {
        reverse_name_map.get(s_key, s_key): stats # 如果原始键未知，则回退到使用清理后的键
        for s_key, stats in cpu_dram_stats_sanitized.items()
        if s_key in reverse_name_map # 只包含已知的键
    }

    # 映射 GPU 统计信息的键
    final_result['gpu_stats'] = {}
    for gpu_idx, s_stats_dict in gpu_stats_sanitized.items():
        mapped_stats = {}
        for s_key, stats in s_stats_dict.items():
            original_key = reverse_name_map.get(s_key, s_key) # 映射回去，回退到使用清理后的键
            mapped_stats[original_key] = stats
        # 确保 'name' 键是正确的 (它应该从 sanitized_gpu_name_col 映射回来)
        final_result['gpu_stats'][gpu_idx] = mapped_stats

    return final_result