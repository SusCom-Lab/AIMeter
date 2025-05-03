# 安装

## 1. 安装依赖

`pip install -r requirements.txt`

## 2. 安装dcgm

`sudo apt-get update`
`sudo apt-get install -y datacenter-gpu-manager`

# 使用

## 1. 如果想存到mysql里，则修改config.py里的数据库配置，如果存到csv里，就不用改了。monitor.py中的’sys.path.append('/home/ldaphome/hhz/workspace/LLM/Metrics_Counter')‘要修改一下。

## 2. 导入

`from Metrics_Counter import monitor, draw`

## 3. 启动
```python
# 任务名： 作用不大，用于标识
# 采样间隔： 最小可以到100ms，受到采样指标和驱动影响
# 输出格式： 目前支持csv和mysql
# 额外指标： 可选值为['CPU','DRAM','Gdetails','fp64','fp32','fp16']
# 监测GPU： 0表示第一个GPU，1表示第二个GPU，2表示第三个GPU，不写等于监测全部GPU

# 名为clean的任务，采样间隔为1ms，输出格式为csv，额外指标为空，监测第0,1,2个GPU
monitor.start(task_name = "clean", sampling_interval = 1, output_format = "csv", additional_metrics=[], indices = [0,1,2]) 
# your_code
monitor.stop()

# 名为clean的任务，采样间隔为0.5ms，输出格式为mysql，额外指标为['CPU','DRAM']，监测所有GPU
monitor.start(task_name = "clean", sampling_interval = 0.5, output_format = "mysql", additional_metrics=['CPU','DRAM'], indices = []) 
# your_code
monitor.stop()

# 名为clean的任务，采样间隔为0.7ms，输出格式为csv，额外指标为['Gdetails']，监测所有GPU
monitor.start(task_name = "clean", sampling_interval = 0.7, output_format = "csv", additional_metrics=['Gdetails'])
# your_code
monitor.stop()

# 名为clean的任务，采样间隔为1ms，输出格式为csv，额外指标为['CPU','DRAM','Gdetails','fp32','fp16']，监测所有GPU
monitor.start(task_name = "clean", sampling_interval = 1, output_format = "csv", additional_metrics=['CPU','DRAM','Gdetails','fp32','fp16'])
# your_code
monitor.stop()
```

指标讲解：

### additional_metrics = []
-  `gpu_power_draw`: GPU 的瞬时功耗，表示 GPU 在采样时刻消耗的电能功率，单位通常是瓦特（W）。
-  `utilization_gpu`: GPU 的核心利用率，表示 GPU 计算核心在过去一段时间内的繁忙程度，以百分比表示。
-  `utilization_memory`: GPU 显存利用率，表示 GPU 显存在过去一段时间内读写操作的繁忙程度，以百分比表示。
-  `pcie_link_gen_current`: 当前 PCIe（Peripheral Component Interconnect Express）链路的代数（Generation），表示 GPU 与主板连接的 PCIe 通道当前运行的速度标准（例如 3, 4, 5）。数字越大通常表示带宽高。
-  `pcie_link_width_current`: 当前 PCIe 链路的宽度，表示 GPU 与主板连接实际使用的 PCIe 通道数量（例如 x8, x16）。宽度越大通常表示带宽高。
-  `temperature_gpu`: GPU 核心的温度，单位通常是摄氏度（°C）。
-  `temperature_memory`: GPU 显存的温度，单位通常是摄氏度（°C）。（注意：并非所有 GPU 都支持报告显存温度）。
-  `clocks_gr`: GPU 图形时钟（Graphics Clock）的当前频率，表示 GPU 核心主要部分的运行速度，单位通常是兆赫兹（MHz）。
-  `clocks_mem`: GPU 显存时钟（Memory Clock）的当前频率，表示 GPU 显存的运行速度，单位通常是兆赫兹（MHz）。
-  `clocks_sm`: GPU 流式多处理器（Streaming Multiprocessor, SM）时钟的当前频率，表示 GPU 内部计算单元集群的运行速度，单位通常是兆赫兹（MHz）。

这些是基本指标

### additional_metrics = [’CPU‘]
-   `cpu_usage`: 中央处理器（CPU）的整体使用率，表示 CPU 在采样时刻的繁忙程度，通常以百分比表示。
-   `cpu_power_draw`: CPU 的瞬时功耗，表示 CPU 在采样时刻消耗的电能功率，单位通常是瓦特（W）。

### additional_metrics = [’DRAM‘]
- `dram_usage`: 动态随机存取存储器（DRAM，即主内存/内存条）的使用率，表示已用内存占总内存的百分比。
- `dram_power_draw`: DRAM 的瞬时功耗，表示内存条在采样时刻消耗的电能功率，单位通常是瓦特（W）。

### additional_metrics = [’Gdetails‘]
| 指标名称                                                             | ID           | 指标类型    | 单位  | 说明                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------------------------------------- | ------------ | ------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DCGM_FI_PROF_SM_ACTIVE                                           | 1002         | Gauge   | %   | 表示在一个时间间隔内，至少一个线程束在一个SM（Streaming Multiprocessor）上处于Active的时间占比。<br>该值表示所有SM的平均值，且该值对每个块的线程数不敏感。<br>线程束处于Active是指一个线程束被调度且分配资源后的状态，可能是在Computing、也可能是非Computing状态（例如等待内存请求）。<br>该值小于0.5表示未高效利用GPU，大于0.8是必要的。<br>假设一个GPU有N个SM：<br>- 一个核函数在整个时间间隔内使用N个线程块运行在所有的SM上，此时该值为1（100%）。<br>- 一个核函数在一个时间间隔内运行N/5个线程块，此时该值为0.2。<br>- 一个核函数使用N个线程块，在一个时间间隔内，仅运行了1/5个周期的时间，此时该值为0.2。 |
| DCGM_FI_PROF_SM_OCCUPANCY                                        | 1003         | Gauge   | %   | 表示在一个时间间隔内，驻留在SM上的线程束与该SM最大可驻留线程束的比例。<br>该值表示一个时间间隔内的所有SM的平均值。<br>占用率越高不代表GPU使用率越高。只有在GPU内存带宽受限的工作负载（DCGM_FI_PROF_DRAM_ACTIVE）情况下，更高的占用率表示更有效的GPU使用率。                                                                                                                                                                                                                   |
| DCGM_FI_PROF_PIPE_TENSOR_ACTIVE                                  | 1004         | Gauge   | %   | 表示Tensor（HMMA/IMMA） Pipe处于Active状态的周期分数。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>较高的值表示Tensor Cores的利用率较高。<br>该值为1（100%）表示在整个时间间隔内每隔一个指令周期发出一个Tensor指令（两个周期完成一条指令）。<br>假设该值为0.2（20%），可能有如下情况：<br>- 在整个时间间隔内，有20%的SM的Tensor Core以100%的利用率运行。<br>- 在整个时间间隔内，有100%的SM的Tensor Core以20%的利用率运行。<br>- 在整个时间间隔的1/5时间内，有100%的SM上的Tensor Core以100%利用率运行。<br>- 其他组合模式。                       || DCGM_FI_PROF_DRAM_ACTIVE                                         | 1005         | Gauge   | %   | 表示内存带宽利用率（Memory BW Utilization）是将数据发送到设备内存或从设备内存接收数据的周期分数。<br>该值表示时间间隔内的平均值，而不是瞬时值。<br>较高的值表示设备内存的利用率较高。<br>该值为1（100%）表示在整个时间间隔内的每个周期执行一条 DRAM 指令（实际上，峰值约为 0.8 (80%) 是可实现的最大值）。<br>假设该值为0.2（20%），表示20%的周期在时间间隔内读取或写入设备内存。                                                                                                                                              |
| - DCGM_FI_PROF_PCIE_TX_BYTES<br>- DCGM_FI_PROF_PCIE_RX_BYTES     | 1009<br>1010 | Counter | B/s | 表示通过PCIe总线传输/接收的数据速率，包括协议标头和数据有效负载。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>该速率在时间间隔内平均。例如，在1秒内传输1 GB数据，则无论以恒定速率还是突发传输数据，速率都是1 GB/s。理论上的最大PCIe Gen3带宽为每通道985 MB/s。                                                                                                                                                                                                                |
| - DCGM_FI_PROF_NVLINK_RX_BYTES<br>- DCGM_FI_PROF_NVLINK_TX_BYTES | 1012<br>1011 | Counter | B/s | 表示通过NVLink传输/接收的数据速率，不包括协议标头。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>该速率在时间间隔内平均。例如，在1秒内传输1 GB数据，则无论以恒定速率还是突发传输数据，速率都是1 GB/s。理论上，最大NVLink Gen2带宽为每个方向每个链路25 GB/s。                                                                                                                                                                                                                |
| DCGM_FI_DEV_MEM_COPY_UTIL                                        | 204          | Gauge   | %   | 表示内存带宽利用率。<br>以英伟达GPU V100为例，其最大内存带宽为900 GB/sec，如果当前的内存带宽为450 GB/sec，则内存带宽利用率为50%。                                                                                                                                                                                                                                                                                      |

### additional_metrics = [’fp64‘]

| DCGM_FI_PROF_PIPE_FP64_ACTIVE                                    | 1006         | Gauge   | %   | 表示FP64（双精度）Pipe处于Active状态的周期分数。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>较高的值代表FP64 Cores有较高的利用率。<br>该值为 1（100%）表示在整个时间间隔内上每四个周期（以Volta类型卡为例）执行一次FP64指令。<br>假设该值为0.2（20%），可能有如下情况：<br>- 在整个时间间隔内，有20%的SM的FP64 Core以100%的利用率运行。<br>- 在整个时间间隔内，有100%的SM的FP64 Core以20%的利用率运行。<br>- 在整个时间间隔的1/5时间内，有100%的SM上的FP64 Core以100%利用率运行。<br>- 其他组合模式。                                         |
| ---------------------------------------------------------------- | ------------ | ------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

### additional_metrics = [’fp32‘]

| DCGM_FI_PROF_PIPE_FP32_ACTIVE                                    | 1007         | Gauge   | %   | 表示乘加操作FMA（Fused Multiply-Add）管道处于Active的周期分数，乘加操作包括FP32（单精度）和整数。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>较高的值代表FP32 Cores有较高的利用率。<br>该值为1（100%）表示在整个时间间隔内上每两个周期（Volta类型卡为例）执行一次FP32指令。<br>假设该值为0.2（20%），可能有如下情况：<br>- 在整个时间间隔内，有20%的SM的FP32 Core以100%的利用率运行。<br>- 在整个时间间隔内，有100%的SM的FP32 Core以20%的利用率运行。<br>- 在整个时间间隔的1/5时间内，有100%的SM上的FP32 Core以100%利用率运行。<br>- 其他组合模式。          |
| ---------------------------------------------------------------- | ------------ | ------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

### additional_metrics = [’fp16‘]

| DCGM_FI_PROF_PIPE_FP16_ACTIVE                                    | 1008         | Gauge   | %   | 表示FP16（半精度）管道处于Active的周期分数。<br>该值表示一个时间间隔内的平均值，而不是瞬时值。<br>较高的值代表FP16 Cores有较高的利用率。<br>该值为 1 (100%) 表示在整个时间间隔内上每两个周期（Volta类型卡为例）执行一次FP16指令。<br>假设该值为0.2（20%），可能有如下情况：<br>- 在整个时间间隔内，有20%的SM的FP16 Core以100%的利用率运行。<br>- 在整个时间间隔内，有100%的SM的FP16 Core以20%的利用率运行。<br>- 在整个时间间隔的1/5时间内，有100%的SM上的FP16 Core以100%利用率运行。<br>- 其他组合模式。                                            |
| ---------------------------------------------------------------- | ------------ | ------- | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

### 额外说明：dcgm是影响采样频率的关键。推荐在追求采样频率时，采样较少的指标。其中，`fp64`,`fp32`,`fp16`影响格外严重。

## 4. 画图
```python

# 将csv文件路径为'/home/ldaphome/hhz/workspace/LLM/clean_20250421_142525.csv'的文件绘制出来
draw.draw_csv(table_path = '/home/ldaphome/hhz/workspace/LLM/clean_20250421_142525.csv')

# 将mysql数据库中的表clean_20250421_133841数据绘制出来，具体数据库的ip和数据库名，可以去config.py中设置，gpu_indices = []表示绘制所有gpu的指标，[0]表示绘制第0个gpu的指标。
draw.draw_mysql(table_name = 'clean_20250421_133841')
```
