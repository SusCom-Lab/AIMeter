# 项目名称
能耗监控工具

## 项目简介

**背景**：当前AI研究领域（尤其是大模型训练、超参数搜索等场景）普遍存在"性能优先"的思维定式，研究者往往将硬件资源视为无限供给的计算单元，对GPU/CPU的能耗特性（如功率波动、热耗散效率）缺乏系统化关注。而随着AI任务对算力需求的指数级增长，硬件资源的能耗效率逐渐成为影响科研成本和环境可持续性的重要因素。因此，如何有效、轻量化的监控能耗相关指标显得十分重要。目前
能耗数据采集主要依赖研究者手动执行nvidia-smi、perf等命令行工具，数据记录与任务执行呈割裂状态，同时还增加了科研人员的调试与优化成本。

**目标**：开发一套自动化、轻量级的跨平台监控工具，实现以下核心功能：

- 实时采集：以可配置的时间间隔捕获CPU/GPU的能耗与性能指标
- 多设备支持：兼容多GPU服务器环境
- 数据持久化：提供CSV和MySQL两种存储方案，适配不同规模的数据管理需求
- 可视化分析：生成交互式图表，直观展示硬件资源利用率与能耗的时空关系

**成果**：实现了一套高可用性能源监控系统，具备以下技术指标：

- 支持1秒级数据采集精度
- 兼容NVIDIA全系列GPU（基于nvidia-smi的标准化输出解析）
- 提供MySQL批量写入优化（事务提交频率可调，单表日均千万级记录处理能力）
- 生成交互式HTML可视化报告（基于Plotly的动态图表，支持多维度数据对比）

## 项目整体实现

### 流程图
![image.png](image.png)

### 1.监控数据采集模块
**GPU指标采集**：通过subprocess调用nvidia-smi命令行工具，解析以下关键参数：

```Python
# 核心监控指标
GPU_QUERY_FIELDS = [
    "name", "index", "power.draw", "utilization.gpu", 
    "utilization.memory", "temperature.gpu", "temperature.memory",
    "clocks.gr", "clocks.mem",
    "pcie.link.width.current", "pcie.link.width.current", "sm"]
```

**CPU指标采集**：基于psutil库实现多核利用率统计：

```Python
def get_cpu_info():
    return psutil.cpu_percent(interval=1, percpu=False)  # 全局平均利用率
```

### 2.数据存储模块
**CSV存储方案**: 采用追加写入模式，文件命名规范：{task_name}_{timestamp}.csv
```Python
# 数据字段与MySQL表结构严格对齐
CSV_COLUMNS = [
    'timestamp', 'task_name', 'cpu_usage', 'gpu_name', 'gpu_index',
    'power_draw', 'utilization_gpu', 'utilization_memory', ...
]
```

**MySQL存储方案**: 动态建表机制（按任务名称+时间戳自动创建），支持InnoDB引擎的事务处理：
```SQL
CREATE TABLE IF NOT EXISTS {table_name} (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '采集时间',
    task_name VARCHAR(50) COMMENT '任务名称',
    gpu_index INT COMMENT 'GPU设备索引',
    sm FLOAT COMMENT 'SM利用率(%)',
    ...
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.可视化模块
动态图表生成基于Plotly库创建包含多个维度的交互式折线图：
```Python
fig.add_trace(go.Scatter(
    x=df['timestamp'], 
    y=df['power_draw'],
    mode='lines',
    name='GPU Power (W)',
    hovertemplate="<b>%{x}</b><br>功率: %{y}W"
))
```

## 项目使用说明

有关详细的项目使用说明，请参见 [UserManual.md](UserManual.md)。