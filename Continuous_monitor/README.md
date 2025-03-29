# 硬件资源持续监控系统

这是一个简单易用的持续监控系统，可以实时监控CPU、GPU等硬件资源的使用情况。

## 功能特点

- 持续监控CPU和GPU性能指标
- 自动保存数据到CSV文件
- 提供简单的一键启动和停止功能
- 无需输入任务和命令参数

## 监控指标

- **CPU**: 使用率、功耗
- **内存**: 使用率、功耗
- **GPU**: 功耗、利用率、内存利用率、温度、时钟频率等

## 系统要求

- Python 3.6+
- NVIDIA显卡（用于GPU监控）
- NVIDIA驱动程序和nvidia-smi工具
- 必要的Python包：pandas, plotly, psutil, deprecated等

## 安装依赖

```bash
pip install pandas plotly psutil deprecated
```

## 使用方法

### 启动监控系统

使用启动脚本一键启动：

```bash

# 如果是首次运行，请给脚本添加执行权限
chmod +x start_monitor.sh stop_monitor.sh

# 启动监控系统
./start_monitor.sh
```

这将在后台启动持续监控，并将日志保存到`monitor.out`文件。

### 停止监控系统

使用停止脚本一键停止：

```bash
./stop_monitor.sh
```

### 手动运行（支持更多参数）

您也可以直接运行Python脚本，并设置自定义参数：

```bash
python continuous_monitor.py -i 3
```

参数说明：
- `-i, --interval`: 采样间隔，单位为秒（默认为1秒）

## 输出文件

- **数据文件**: 保存在`monitor_data`目录下，CSV格式
- **日志文件**: `continuous_monitor.log`、`monitor.out`（启动脚本生成）

## 常见问题排查

- **找不到nvidia-smi命令**: 请确保已正确安装NVIDIA驱动程序
- **无法正常启动**: 检查`monitor.out`和`continuous_monitor.log`日志文件
- **ModuleNotFoundError**: 请确保安装了所有必要的依赖包（pandas, plotly, psutil, deprecated）

## 注意事项

- 目前每次运行都会产生一个新的csv文档存储数据
- 长时间运行可能会生成大量数据，请定期清理不需要的数据文件