# 实时 CPU 和 GPU 监控工具

## 概述
本工具可实时监控 CPU 和 GPU 的数据，根据用户的选择，将数据保存至 csv 文件或者 MySQL 数据库中，并根据保存的 csv 文件或者 Mysql 数据库中的表格生成可视化图表。它专为需要分析系统性能的用户而设计。

以下为监控的数据：
- cpu_usage：CPU 使用率。
- gpu_name：GPU 的名称。
- gpu_index：GPU 在系统中的索引编号。
- power_draw：当前 GPU 的功耗。
- utilization_gpu：GPU 核心的利用率。
- utilization_memory：GPU 显存的使用率。
- pcie_link_gen_current：GPU 当前使用的 PCIe 代数，例如 3、4、5。
- pcie_link_width_current：GPU 当前使用的 PCIe 通道宽度，例如 1、4、8、16。
- temperature_gpu：GPU 核心温度。
- temperature_memory：GPU 显存温度。
- sm（Streaming Multiprocessors）：GPU 的流式多处理器（SM）的使用率。
- clocks_gr : GPU 时钟频率。
- clocks_mem : GPU 显存时钟频率。

说明：目前默认，记录的 CPU 和 GPU 上的利用率和功率等信息均为一个用户的一个任务所产生的，无法识别并行状态下，不同任务各自的利用率和功率等信息。

## 功能特点
- 实时监控 CPU 和 GPU 统计数据。
- 自动将数据记录到 csv文件或者 MySQL 数据库中。
- 支持使用 `plotly` 进行数据可视化。
- 监控间隔可配置。

## 文件目录
- `monitor.py`: 监控工具脚本
- `requirements.txt`: 依赖
- `UserManual.md`: 用户使用手册
- `Readme.md`: 项目说明文档

## 使用方法

###  步骤一：在环境中安装依赖（在待提交任务的环境中安装）

`pip install -r requirements.txt`

如果在后续运行时出现`mysql`连接相关问题，需要对`mysql`进行升级:

``pip install --upgrade mysql-connector-python``

###  步骤二：将`monitor.py`脚本复制到待提交任务的同级目录下

###  步骤三：运行脚本进行监控，同时传入待提交任务运行命令

说明：脚本需要在 要被监控的服务器 上运行。

运行脚本提交任务同时开始监控：
```bash
python monitor.py monitor -n "task_name" -t 1/10/…… -cmd "Command to execute for the task" -o "csv/mysql"
```

参数说明：

monitor: 使用监控功能
- n: 任务名称（用于标识）
- t: 采样时间间隔（默认为10s）
- cmd: 提交任务命令
- o: 存储方式（默认为csv）

脚本将会：
- 在当前文件所在目录下创建`monitor.log`日志文件
- 在当前文件所在目录下创建`task_name_timestamp.csv`文件 或 在管理节点的mysql数据库 `monitor` 中创建表 `task_name_timestamp`(根据 `o` 参数进行选择)。
- 提交任务。
- 将实时检测数据保存到 文件`task_name_timestamp.csv` 或 表`task_name_timestamp` 中。
- 任务结束后自动终止脚本，停止检测。

**文件名可在`monitor.log`中查看得到**

一个例子：
```bash
python monitor.py monitor -n "fine_tuning_for_llama2_7b" -t 10 -cmd "python finetuning.py" -o "csv"
```

参数解释：

- python monitor.py monitor：调用 monitor.py 这个 Python 脚本，并执行 monitor 监控功能。
- n "fine_tuning_for_llama2_7b"：指定任务名称 fine_tuning_for_llama2_7b，用于标识监控的任务，并作为 CSV 文件或数据库表的名称。
- t 10：设置采样时间间隔为 10 秒，即每 10 秒记录一次系统资源使用情况。
- cmd "python finetuning.py"：提交并执行 python finetuning.py 这个任务，finetuning.py 是 LLaMA 2 7B 的微调脚本。
- o "csv"：将监控数据存储到 CSV 文件 中，而不是 MySQL 数据库。

### 步骤四：生成可视化图表
运行可视化函数来创建图表：
```bash
python monitor.py plot -t "table_name" -f "csv/mysql"
```

参数说明：

plot: 使用画图功能
- t: 表名
- f: 表的格式（默认为csv）

这将会使用 `plotly` 生成交互式图表，在浏览器中显示出来，同时也生成`html`文件保存到目录`monitor_ghraphs`下。

两个例子：
```bash
python monitor.py plot -t "fine_tunning_for_llama2_7b_20250112_202325" -f "mysql"
```

- python monitor.py plot：调用 monitor.py 的 绘图 功能。
- t "fine_tunning_for_llama2_7b_20250112_202325"：指定要绘图的数据表名称，这里数据存储在 MySQL 数据库 中，表名为 fine_tunning_for_llama2_7b_20250112_202325。
- f "mysql"：指定数据来源是 MySQL 数据库。

```bash
python monitor.py plot -t "fine_tuning_for_llama2_7b_20250204_154110.csv" -f "csv"
```

- python monitor.py plot：调用 monitor.py 的 绘图 功能。
- t "fine_tuning_for_llama2_7b_20250204_154110.csv"：指定要绘图的文件名称，这里数据存储在 CSV 文件 中，文件名为 fine_tuning_for_llama2_7b_20250204_154110.csv。
- f "csv"：指定数据来源是 CSV 文件。

## 日志
日志默认存储在 `monitor.log` 文件中。查看该文件可获取有关错误和系统活动的详细信息。

