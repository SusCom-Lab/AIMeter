import os
import threading
import time
import signal
import logging
import argparse
from datetime import datetime

# 导入原脚本中的功能
from monitor import (
    get_gpu_info,
    get_cpu_usage_info,
    get_cpu_power_info,
    get_dram_usage_info,
    get_dram_power_info,
    parallel_collect_metrics,
    fetch_and_plot_data
)

# 设置日志配置
logging.basicConfig(
    filename="continuous_monitor.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 全局变量
inserted_count = 0
running = True
output_dir = "monitor_data"

def signal_handler(sig, frame):
    """处理SIGINT和SIGTERM信号，优雅地停止监控"""
    global running
    print("\n正在停止监控系统...")
    running = False

def ensure_directories():
    """确保所有必要的目录都存在"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"创建数据输出目录: {output_dir}")
    

def save_to_csv(metrics, csv_file, time_stamp):
    """将监控数据保存到CSV文件"""
    global inserted_count
    
    # 检查文件是否存在，不存在则创建并写入表头
    file_exists = os.path.isfile(csv_file)
    
    try:
        with open(csv_file, mode='a', newline='', encoding='utf-8') as f:
            # 定义字段
            fieldnames = [
                'timestamp', 'cpu_usage', 'cpu_power_draw', 'dram_usage', 'dram_power_draw', 
                'gpu_name', 'gpu_index', 'gpu_power_draw', 'utilization_gpu', 'utilization_memory',
                'pcie_link_gen_current', 'pcie_link_width_current', 'temperature_gpu', 
                'temperature_memory', 'clocks_gr', 'clocks_mem', 'clocks_sm'
            ]
            
            # 如果文件不存在，写入表头
            if not file_exists:
                header = ','.join(fieldnames) + '\n'
                f.write(header)
            
            # 为每个GPU添加一行数据
            gpu_info = metrics.get('gpu_info', [])
            cpu_usage = metrics.get('cpu_usage', 'N/A')
            cpu_power = metrics.get('cpu_power', 'N/A')
            dram_usage = metrics.get('dram_usage', 'N/A')
            dram_power = metrics.get('dram_power', 'N/A')
            
            for gpu in gpu_info:
                # 处理温度数据
                temp_gpu = gpu.get('temperature.gpu', 'N/A')
                temp_memory = gpu.get('temperature.memory', 'N/A')
                
                # 构建行数据
                row_data = [
                    time_stamp,
                    f"{cpu_usage:.2f} %" if cpu_usage != 'N/A' else 'N/A',
                    f"{cpu_power:.2f} W" if cpu_power != 'N/A' else 'N/A',
                    f"{dram_usage:.2f} %" if dram_usage != 'N/A' else 'N/A',
                    f"{dram_power:.2f} W" if dram_power != 'N/A' else 'N/A',
                    f"{gpu.get('name', 'N/A')}",
                    str(gpu.get('index', 0)),
                    f"{gpu.get('power.draw [W]', 'N/A')}",
                    f"{gpu.get('utilization.gpu [%]', 'N/A')}",
                    f"{gpu.get('utilization.memory [%]', 'N/A')}",
                    f"{gpu.get('pcie.link.gen.current', 'N/A')}",
                    f"{gpu.get('pcie.link.width.current', 'N/A')}",
                    f"{temp_gpu} °C" if temp_gpu != 'N/A' else "N/A",
                    f"{temp_memory} °C" if temp_memory != 'N/A' else "N/A",
                    f"{gpu.get('clocks.current.graphics [MHz]', 'N/A')}",
                    f"{gpu.get('clocks.current.memory [MHz]', 'N/A')}",
                    f"{gpu.get('clocks.current.sm [MHz]', 'N/A')}"
                ]
                
                # 写入CSV
                f.write(','.join(row_data) + '\n')
                inserted_count += 1
        
        if inserted_count % 10 == 0:
            logging.info(f"已写入 {inserted_count} 条记录")
            
    except Exception as e:
        logging.error(f"保存到CSV时出错: {e}")

def continuous_monitor(interval, plot_interval):
    """
    持续监控系统资源
    
    参数:
        interval (float): 监控采样间隔（秒）
        plot_interval (int): 生成图表的间隔（采样次数）
    """
    global running
    
    # 设置信号处理器用于捕获Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 确保目录存在
    ensure_directories()
    
    # 创建文件名，使用当前时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(output_dir, f"continuous_monitor_{timestamp}.csv")
    
    sample_count = 0
    print(f"持续监控已启动，数据将保存至: {csv_file}")
    print("按 Ctrl+C 停止监控")
    
    try:
        while running:
            start_time = time.time()
            
            # 获取当前时间戳
            time_stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-5]
            
            # 并行采集所有指标
            metrics = parallel_collect_metrics()
            
            # 检查数据有效性
            if metrics["gpu_info"] is None:
                logging.warning("没有可用的GPU信息，跳过本次采集")
                time.sleep(interval)
                continue
                
            if metrics["cpu_usage"] is None:
                logging.warning("获取CPU信息失败，跳过本次采集")
                time.sleep(interval)
                continue
            
            # 保存到CSV
            save_to_csv(metrics, csv_file, time_stamp)
            
            # 更新计数器
            sample_count += 1
            
            
            # 计算剩余等待时间
            elapsed_time = time.time() - start_time
            sleep_time = max(0, interval - elapsed_time)
            
            # 等待下一次采样
            time.sleep(sleep_time)
            
    except Exception as e:
        logging.error(f"监控过程中发生错误: {e}")
    finally:

        print(f"监控已停止，共采集 {sample_count} 个样本")
        print(f"数据已保存至: {csv_file}")

def main():
    parser = argparse.ArgumentParser(description="持续监控系统资源")
    parser.add_argument("-i", "--interval", type=float, default=5,
                      help="采样间隔（秒），默认5秒")
    parser.add_argument("-p", "--plot_interval", type=int, default=12,
                      help="生成图表的间隔（采样次数），默认12次（约1分钟）")
    
    args = parser.parse_args()
    
    continuous_monitor(args.interval, args.plot_interval)

if __name__ == "__main__":
    main() 