import sys
# 这里的路径需要根据实际情况进行调整
sys.path.append('__file__' + '/..')
import time
from datetime import datetime
import threading
from metrics_collect import parallel_collect_metrics
from metrics_calculate import calculate_metrics, calculate_metrics_from_mysql
from save import save_to_csv, save_to_mysql
import state
from resources_consumption_record import get_average_time, get_max_time, monitor_resources
from get_carbon_density import get_current_carbon_intensity, compute_carbon_emission
import math
# --- 格式化常量 ---
# 指标标签的宽度（例如："cpu_usage", "power.draw [W]"）
LABEL_WIDTH = 30
# 每个统计值的宽度（平均值、最大值、最小值、众数）
VALUE_WIDTH = 20
# 分隔线长度
SEPARATOR_LEN = 146

def _safe_float(value, default=None):
    """安全地将值转换为浮点数，处理'N/A'或错误情况"""
    if isinstance(value, (int, float)) and not math.isnan(value):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def _format_value(value, width=VALUE_WIDTH, precision=2):
    """将单个值（数字或像'N/A'这样的字符串）格式化为固定宽度"""
    num_value = _safe_float(value)
    if num_value is not None:
        # 使用指定精度格式化数字
        formatted_val = f"{num_value:.{precision}f}"
    else:
        # 处理'N/A'或其他非数字字符串
        formatted_val = str(value)
    # 将格式化后的值填充到所需宽度
    return f"{formatted_val:<{width}}"

def _format_stat_dict(stat_dict: dict | str | int | float, key_name: str = "", total_time: str | float = "N/A") -> str:
    """
    将统计信息字典或单个值格式化为具有对齐列的可读字符串。
    """

    # 处理简单的非字典值（如 PCIe 链接信息）
    if not isinstance(stat_dict, dict):
        # 仅返回值，为保持一致性稍作填充
        return str(stat_dict) # 这里不需要复杂的对齐

    # 格式化标准统计字典（平均值、最大值、最小值、众数）
    mean = stat_dict.get('mean', 'N/A')
    max_val = stat_dict.get('max', 'N/A')
    min_val = stat_dict.get('min', 'N/A')
    mode_val = stat_dict.get('mode', 'N/A')

    # 如果所有统计值都是'N/A'，则返回简单的'N/A'
    if all(v == 'N/A' for v in [mean, max_val, min_val, mode_val]):
        return "N/A"

    # 使用固定宽度格式化每个部分以实现对齐
    mean_str = f"Avg: {_format_value(mean)}"
    max_str = f"Max: {_format_value(max_val)}"
    min_str = f"Min: {_format_value(min_val)}"
    mode_str = f"Mode: {_format_value(mode_val)}"

    # 组合对齐后的各个部分
    return f"{mean_str} {max_str} {min_str} {mode_str}"


# 打印格式化后的性能指标
def print_formatted_metrics(metrics: dict[str, any], task_name: str):
    """
    以结构化、对齐且更美观的方式打印计算得到的性能指标。
    参数:
        metrics (Dict[str, Any]): 由 calculate_metrics 返回的指标字典。
        task_name (str): 被监控的任务名称。
    """
    if not metrics:
        print("\n[Error] 指标数据为空或无效，无法打印格式化结果。\n")
        return

    # 安全获取各部分指标
    cpu_dram_stats = metrics.get('cpu_dram_stats', {})
    gpu_stats = metrics.get('gpu_stats', {})
    total_time = metrics.get('total_time', 'N/A')
    energy_consumption = metrics.get('energy_consumption', {})

    # 打印页眉
    print("\n" + "=" * SEPARATOR_LEN)
    # print(f"📊 {'任务：' + repr(task_name) + ' 的性能指标汇总':^{SEPARATOR_LEN-16}} 📊") # 居中标题
    # 写成英文
    print(f"📊 {'Task: ' + repr(task_name) + ' Performance Metrics Summary':^{SEPARATOR_LEN-8}} 📊") # 居中标题
    print("=" * SEPARATOR_LEN)

    # 打印总览部分
    # print("\n[ 🕒 总览：总耗时与能耗 ]")
    # 写成英文
    print("\n[ 🕒 Overview: Total Time and Energy Consumption ]")
    # total_time_float = _safe_float(total_time)
    # total_time_str = f"{total_time_float:.2f} S" if total_time_float is not None else "N/A"
    # print(f"  {'任务总耗时':<{LABEL_WIDTH}}: {total_time}")
    # 写成英文
    # 把total_time的秒转换为second
    print(f"  {'Total Time':<{LABEL_WIDTH}}: {total_time.replace('秒', 'S')}")
    print("-" * (SEPARATOR_LEN // 2)) # 较短的分隔线

    # 格式化能耗值
    # print(f"  {'CPU 能耗':<{LABEL_WIDTH}}: {_format_value(energy_consumption.get('cpu_energy'), precision=3)} Joules")
    # print(f"  {'DRAM 能耗':<{LABEL_WIDTH}}: {_format_value(energy_consumption.get('dram_energy'), precision=3)} Joules")
    # # 写成英文
    print(f"  {'CPU Energy':<{LABEL_WIDTH}}: {_format_value(energy_consumption.get('cpu_energy'), precision=3)}")
    print(f"  {'DRAM Energy':<{LABEL_WIDTH}}: {_format_value(energy_consumption.get('dram_energy'), precision=3)}")


    gpu_energy = energy_consumption.get('gpu_energy', {})
    if gpu_energy:
        # 按GPU索引数值排序后打印
        for gpu_idx in sorted(gpu_energy.keys(), key=lambda x: int(x) if str(x).isdigit() else float('inf')):
            energy = gpu_energy[gpu_idx]
            # print(f"  {f'GPU {gpu_idx} 能耗':<{LABEL_WIDTH}}: {_format_value(energy, precision=3)} Joules")
            # 写成英文
            print(f"  {f'GPU {gpu_idx} Energy':<{LABEL_WIDTH}}: {_format_value(energy, precision=3)}")

    # print(f"  {'总能耗':<{LABEL_WIDTH-1}}: {_format_value(energy_consumption.get('total_energy'), precision=3)} Joules")
    # 写成英文
    print(f"  {'Total Energy':<{LABEL_WIDTH}}: {_format_value(energy_consumption.get('total_energy'), precision=3)}")
    if state._position_use == 1:
        result = get_current_carbon_intensity(username="xxx", password="xxx", latitude=state._latitude, longitude=state._longitude)
        lbs, kg = compute_carbon_emission(float(energy_consumption.get('total_energy').replace(" J", "")), result['value'])
        print(f"  {'Carbon Emissions':<{LABEL_WIDTH}}: {kg:.4f} kg CO2eq")

    # 打印CPU/DRAM统计信息
    # print("\n[ 🖥️ CPU 和 DRAM 统计信息 ]")
    # 写成英文
    print("\n[ 🖥️ CPU and DRAM Statistics ]")
    print("-" * (SEPARATOR_LEN // 2))
    if cpu_dram_stats:
        # 指定CPU/DRAM指标的显示顺序
        cpu_dram_order = ['cpu_usage', 'cpu_power', 'dram_usage', 'dram_power'] # 示例名称，根据需要调整
        # 添加未在首选顺序中的其他CPU/DRAM指标
        other_keys = [k for k in cpu_dram_stats if k not in cpu_dram_order]
        
        # 首先按照首选顺序打印
        printed_any = False
        for metric in cpu_dram_order:
            if metric in cpu_dram_stats:
                stats = cpu_dram_stats[metric]
                formatted_stats = _format_stat_dict(stats, key_name=metric, total_time=total_time)
                print(f"  {metric:<{LABEL_WIDTH}}: {formatted_stats}")
                printed_any = True
        
        # 打印剩余指标
        for metric in other_keys:
             stats = cpu_dram_stats[metric]
             formatted_stats = _format_stat_dict(stats, key_name=metric, total_time=total_time)
             print(f"  {metric:<{LABEL_WIDTH}}: {formatted_stats}")
             printed_any = True

        if not printed_any:
             print("  (无有效的 CPU/DRAM 统计数据)")

    else:
        print("  (无 CPU/DRAM 统计信息)")

    # 打印GPU统计信息
    # print("\n[ 🚀 GPU 详细统计信息 ]")
    # 写成英文
    print("\n[ 🚀 GPU Detailed Statistics ]")
    if not gpu_stats:
        print("-" * (SEPARATOR_LEN // 2))
        print("  (无 GPU 统计信息)")
    else:
        # 定义GPU指标分类（根据实际数据调整键值）
        # 这里使用更通用的键值，需要根据calculate_metrics的实际键值替换
        gpu_sections = {
            "Energy Section": [
                'power.draw [W]',
                'temperature.gpu',
            ],
            "Compute Section": [
                'utilization.gpu [%]',
                'clocks.current.graphics [MHz]',
                'clocks.current.sm [MHz]',
                'sm_active',
                'sm_occupancy',
                'tensor_active',
                'fp64_active',
                'fp32_active',
                'fp16_active',
            ],
            "Memory Section": [
                'utilization.memory [%]',
                'temperature.memory',
                'clocks.current.memory [MHz]',
                'usage.memory [%]',
                'dram_active',
            ],
            "Communication Section": [
                'pcie.link.gen.current',
                'pcie.link.width.current',
                'pcie_tx_bytes',
                'pcie_rx_bytes',
                'nvlink_tx_bytes',
                'nvlink_rx_bytes',
            ]
        }

        # 对GPU索引进行数值排序以保持输出顺序一致
        sorted_gpu_indices = sorted(gpu_stats.keys(), key=lambda x: int(x) if str(x).isdigit() else float('inf'))

        for i, gpu_idx in enumerate(sorted_gpu_indices):
            gpu_data = gpu_stats[gpu_idx]
            gpu_name = gpu_data.get('name', '未知名称')

            # 为每个GPU打印清晰的分隔符和标题
            if i > 0: # 从第二个GPU开始添加额外空行
                print("\n" + "~" * (SEPARATOR_LEN // 2) + "\n") # 使用不同的分隔符
            else:
                print("-" * (SEPARATOR_LEN // 2)) # 初始分隔符

            print(f"  --- GPU {gpu_idx} ({gpu_name}) ---")

            # 遍历定义的分类
            for section_name, metric_keys in gpu_sections.items():
                section_has_data = False
                section_output = [] # 存储该分类的输出行

                for key in metric_keys:
                    if key in gpu_data:
                        stats_or_value = gpu_data[key]
                        # 使用改进的_format_stat_dict处理对齐和带宽
                        formatted_value = _format_stat_dict(stats_or_value, key_name=key, total_time=total_time)

                        # 将格式化的行添加到分类输出中
                        section_output.append(f"    {key:<{LABEL_WIDTH}}: {formatted_value}")
                        section_has_data = True

                # 仅在有数据时打印分类标题和数据
                if section_has_data:
                    print(f"\n    [{section_name}]") # 在分类标题前添加空行
                    for line in section_output:
                        print(line)

    # 打印页脚
    print("\n" + "=" * SEPARATOR_LEN)
    # print("📊 指标汇总结束 📊".center(SEPARATOR_LEN))
    # 写成英文
    print("📊 Summary of Metrics Collection Ended 📊".center(SEPARATOR_LEN))
    print("=" * SEPARATOR_LEN + "\n")

def _monitor_stats(additional_metrics,indices):
    """
    内部函数：循环采集数据直到 _monitor_running 被置为 False
    """
    while state._monitor_running:
        try:
            start_time = time.time()
            # 用于数据插入的时间戳，精确到毫秒
            time_stamp_insert = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]
            # 并行采集所有指标
            metrics = parallel_collect_metrics(additional_metrics,indices)
            # 检查必要指标是否采集成功
            if metrics["gpu_info"] is None:
                print("未能采集到部分指标，跳过本次采样。")
                time.sleep(state._sampling_interval)
                continue

            # 根据输出格式调用保存函数
            if state._output_format == "csv":
                save_to_csv(state._task_name, metrics, state._timestamp, time_stamp_insert)
            elif state._output_format == "mysql":
                save_to_mysql(state._task_name, metrics, state._timestamp, time_stamp_insert)
            else:
                print(f"未知的输出格式：{state._output_format}")
                break

            elapsed_time = time.time() - start_time
            state._execution_times['elapsed_time'].append(elapsed_time)

            remaining_time = max(0, state._sampling_interval - elapsed_time)
            time.sleep(remaining_time)
        except Exception as e:
            print(f"监控过程中出现错误: {e}")
            time.sleep(state._sampling_interval)

# @monitor_resources(
#     log_file="resource_monitor.log",
#     monitor_cpu=True,
#     monitor_mem=True,
#     monitor_disk=True,
#     disk_device="sda3"
# )
def start(task_name: str, sampling_interval: float = 1, output_format: str = "csv", additional_metrics: list = [], indices: list = [], position = ()):
    """
    启动监控：开始采集数据
    :param task_name: 任务名称，用于标识记录（同时作为保存数据的文件/表名的一部分）
    :param sampling_interval: 采样时间间隔（秒）
    :param output_format: 输出格式，支持 'csv' 或 'mysql'
    :param additional_metrics: 额外的指标列表，支持 'fp64_active', 'fp32_active', 'fp16_active''
    """
    if state._monitor_running:
        print(f"-----------------------------------------------------------------------------------------------------------------")
        print("监控工具已经在运行。")
        print(f"-----------------------------------------------------------------------------------------------------------------")
        return
    state._task_name = task_name
    state._sampling_interval = sampling_interval
    state._output_format = output_format.lower()
    state._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    state._monitor_running = True
    state._monitor_thread = threading.Thread(target=_monitor_stats, args=(additional_metrics,indices,), daemon=True)
    state._monitor_thread.start()
    if position and len(position) == 2:
        state._position_use = 1
        state._latitude = position[0]
        state._longitude = position[1]
    # 控制台输出
    print(f"-----------------------------------------------------------------------------------------------------------------")
    # print(f"监控工具已启动，正在监控任务 '{state._task_name}' ,采样间隔为 {state._sampling_interval} 秒，输出格式为 '{state._output_format}'。")
    # print(f"任务 '{state._task_name}' 运行结束后，监控工具将停止运行。")
    # 写成英文
    print(f"Monitoring tool started, monitoring task '{state._task_name}', sampling interval is {state._sampling_interval} seconds, output format is '{state._output_format}'.")
    print(f"After the task '{state._task_name}' ends, the monitoring tool will stop running.")
    print(f"-----------------------------------------------------------------------------------------------------------------")

def stop():
    """
    结束监控：停止采集数据
    """
    if not state._monitor_running:
        print(f"-----------------------------------------------------------------------------------------------------------------")
        print("监控工具没有在运行。")
        print(f"-----------------------------------------------------------------------------------------------------------------")
        return
    state._monitor_running = False
    state._monitor_thread.join()
    # 以下整段为输出的简略数据
    if state._output_format == "csv":
        print(f"-----------------------------------------------------------------------------------------------------------------")
        # print(f"任务 '{state._task_name}' 已结束，监控工具停止，共采集{state._inserted_count}个样本，详细数据将保存至:{state._csv_file_path}，简略数据如下：")
        # 写成英文
        print(f"Task '{state._task_name}' has ended, the monitoring tool has stopped, and {state._inserted_count} samples have been collected. Detailed data will be saved to: {state._csv_file_path}, and the summary data is as follows:")
        metrics = calculate_metrics(state._csv_file_path)
        if metrics: # 确保 metrics 不是空的
            print_formatted_metrics(metrics, state._task_name)
    elif state._output_format == "mysql":
        print(f"-----------------------------------------------------------------------------------------------------------------")
        # print(f"任务 '{state._task_name}' 已结束，监控工具停止，共采集{state._inserted_count}个样本，详细数据将保存至:{state._table_name}，简略数据如下：")
        # 写成英文
        print(f"Task '{state._task_name}' has ended, the monitoring tool has stopped, and {state._inserted_count} samples have been collected. Detailed data will be saved to: {state._table_name}, and the summary data is as follows:")
    
        metrics = calculate_metrics_from_mysql(state._table_name)
        if metrics: # 确保 metrics 不是空的
            print_formatted_metrics(metrics, state._task_name)
    # print(get_average_time('parallel_collect_metrics'))
    # print(get_max_time('parallel_collect_metrics'))
    # print(get_average_time('elapsed_time'))
    # print(get_max_time('elapsed_time'))
    state._inserted_count = -1 # 用于记录已插入的行数
    state._csv_file_path = "" # 用于记录CSV文件路径
    state._table_name = "" # 用于记录MYSQL的表格名称
    state._monitor_thread = None # 用于记录监控线程
    state._task_name = ""  # 用于记录任务名称
    state._sampling_interval = 10  # 采样间隔
    state._output_format = "csv"  # 输出格式，支持csv和mysql
    state._timestamp = ""  # 用于记录时间戳
    state._execution_times = {} # 用于保存每个函数的执行时间
    state._execution_times['elapsed_time'] = [] # 专门用于记录采样频率的key-value对
    state._position_use = 0 # 用于记录位置使用情况
    state._latitude = 37.7749 # 用于记录纬度
    state._longitude = -122.4194 # 用于记录经度
