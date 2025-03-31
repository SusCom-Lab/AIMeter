# 实时 CPU 和 GPU 监控工具

## 概述
该工具提供实时监控 CPU 和 GPU 数据的功能。根据用户的选择，数据可以保存到 CSV 文件或 MySQL 数据库，并基于保存的 CSV 文件或 MySQL 表生成可视化图表。该工具专为需要分析系统性能的用户设计。

监控的数据包括：
- cpu_usage: CPU 使用率百分比。
- cpu_power_draw: CPU 当前功耗。
- dram_usage: DRAM 内存使用率百分比。
- dram_power_draw: DRAM 当前功耗。
- gpu_name: GPU 名称。
- gpu_index: 系统中 GPU 的索引号。
- gpu_power_draw: GPU 当前功耗。
- utilization_gpu: GPU 核心利用率百分比。
- utilization_memory: GPU 内存利用率百分比。
- pcie_link_gen_current: GPU 当前使用的 PCIe 代数，例如 3、4、5。
- pcie_link_width_current: GPU 当前使用的 PCIe 通道宽度，例如 1、4、8、16。
- temperature_gpu: GPU 核心温度。
- temperature_memory: GPU 内存温度。
- clocks_gr: GPU 时钟频率。
- clocks_mem: GPU 内存时钟频率。
- clocks_sm: GPU SM 时钟频率。

注意：目前记录的 CPU 和 GPU 利用率及功耗数据仅针对单个用户任务，不区分同时运行的并行任务。

## 功能
- 实时监控 CPU 和 GPU 统计数据。
- 自动将数据记录到 CSV 文件或 MySQL 数据库。
- 支持使用 `plotly` 进行数据可视化。
- 可配置的监控间隔。

## 文件目录
- `monitor.py`: 监控工具脚本。
- `requirements.txt`: 依赖项。
- `UserManual.md`: 用户手册。
- `Readme.md`: 项目文档。
- `monitor.sh`: 监控脚本。
- `plot.sh`: 可视化脚本。
- `Continuous_monitor`: 持续监控项目。
- `ecmhongz`: 用于打包的文件夹。

## 使用方法

### 第一步：在任务将被提交的环境中安装依赖项

`pip install -r requirements.txt`

如果在执行过程中出现 MySQL 连接相关问题，请升级 MySQL：

``pip install --upgrade mysql-connector-python``

### 第二步：将 `monitor.py` 脚本复制到将提交任务的同一目录中。

### 第三步：运行脚本进行监控，并传递任务执行命令

注意：脚本需要在被监控的服务器上运行。

注意：对于指标 `cpu_power_draw` 和 `dram_power_draw`，它们通过 RAPL 接口访问。如果值显示为 `N/A`，则需要管理员权限授予读取权限。需要修改权限的文件如下：

```bash
(llama) (base) hhz@node2:~/workspace/LLM$ ls /sys/class/powercap
dtpm  intel-rapl  intel-rapl:0  intel-rapl:0:0  intel-rapl:1  intel-rapl:1:0
```  

需要修改读取权限的文件包括：`intel-rapl:0`、`intel-rapl:0:0`、`intel-rapl:1` 和 `intel-rapl:1:0`。

运行脚本提交任务并开始监控：
```bash
python monitor.py monitor -n "task_name" -t 0.5/1/3/... -cmd "Command to execute for the task" -o "csv/mysql"
```

参数说明：
- monitor: 激活监控功能。
- n: 任务名称（用于标识）。
- t: 采样间隔。
- cmd: 执行任务的命令。
- o: 存储类型（默认是 csv）。

脚本将会：
- 在当前目录中创建一个 `monitor.log` 日志文件。
- 创建一个 `task_name_timestamp.csv` 文件，或在 MySQL 的 `monitor` 数据库中创建一个名为 `task_name_timestamp` 的表（基于 `o` 参数）。
- 提交任务。
- 将实时监控数据保存到文件 `task_name_timestamp.csv` 或表 `task_name_timestamp`。
- 在任务结束后，自动终止脚本并停止监控。

**文件名可以在 `monitor.log` 中找到。**

示例：
```bash
python monitor.py monitor -n "fine_tuning_for_llama2_7b" -t 10 -cmd "python finetuning.py" -o "csv"
```

参数解释：
- `python monitor.py monitor`: 调用 `monitor.py` 脚本并执行监控功能。
- `n "fine_tuning_for_llama2_7b"`: 指定任务名称 `fine_tuning_for_llama2_7b`，用于标识以及作为 CSV 文件或数据库表的名称。
- `t 10`: 设置采样间隔为 10 秒，即每 10 秒记录一次系统资源使用情况。
- `cmd "python finetuning.py"`: 提交并执行命令 `python finetuning.py`，其中 `finetuning.py` 是用于微调 LLaMA 2 7B 的脚本。
- `o "csv"`: 将监控数据存储在 CSV 文件中，而不是 MySQL 数据库中。

### 第四步：生成可视化图表
运行可视化功能生成图表：
```bash
python monitor.py plot -t "table_name" -f "csv/mysql"
```

参数说明：
- plot: 激活绘图功能。
- t: 表名。
- f: 表格式（默认是 csv）。

这将使用 `plotly` 生成一个交互式图表，图表将在浏览器中显示，并以 `html` 文件的形式保存在 `monitor_graphs` 目录中。

两个示例：
```bash
python monitor.py plot -t "fine_tunning_for_llama2_7b_20250112_202325" -f "mysql"
```

- `python monitor.py plot`: 调用 `monitor.py` 脚本并激活绘图功能。
- `t "fine_tunning_for_llama2_7b_20250112_202325"`: 指定表名，从 MySQL 数据库中绘制数据，表名为 `fine_tunning_for_llama2_7b_20250112_202325`。
- `f "mysql"`: 指定数据来源为 MySQL。

```bash
python monitor.py plot -t "fine_tuning_for_llama2_7b_20250204_154110.csv" -f "csv"
```

- `python monitor.py plot`: 调用 `monitor.py` 脚本并激活绘图功能。
- `t "fine_tuning_for_llama2_7b_20250204_154110.csv"`: 指定文件名，从 CSV 文件中绘制数据，文件名为 `fine_tuning_for_llama2_7b_20250204_154110.csv`。
- `f "csv"`: 指定数据来源为 CSV。

## 日志
日志默认存储在 `monitor.log` 文件中。检查此文件以获取有关错误和系统活动的详细信息。
