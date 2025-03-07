import time
import functools
import threading
import psutil
import logging
from typing import Callable

# 用于保存每个函数的执行时间
execution_times = {}
execution_times['elapsed_time'] = []

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