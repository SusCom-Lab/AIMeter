# Real-time CPU and GPU Monitoring Tool

## Overview
This tool provides real-time monitoring of CPU and GPU data. Based on the user's selection, the data can be saved to a CSV file or MySQL database, and visualized into charts based on the saved CSV file or MySQL table. It is designed for users who need to analyze system performance.

The data monitored includes:
- cpu_usage: CPU usage percentage.
- cpu_power_draw: Current power consumption of the CPU.
- dram_usage: DRAM memory usage percentage.
- dram_power_draw: Current power consumption of the DRAM.
- gpu_name: GPU name.
- gpu_index: Index number of the GPU in the system.
- gpu_power_draw: Current power consumption of the GPU.
- utilization_gpu: GPU core utilization percentage.
- utilization_memory: GPU memory utilization percentage.
- pcie_link_gen_current: Current PCIe generation used by the GPU, such as 3, 4, 5.
- pcie_link_width_current: Current PCIe lane width used by the GPU, such as 1, 4, 8, 16.
- temperature_gpu: GPU core temperature.
- temperature_memory: GPU memory temperature.
- sm (Streaming Multiprocessors): GPU Streaming Multiprocessor (SM) utilization.
- clocks_gr: GPU clock frequency.
- clocks_mem: GPU memory clock frequency.

Note: Currently, the recorded CPU and GPU utilization and power data are for a single user's task and do not differentiate between parallel tasks running simultaneously. 

## Features
- Real-time monitoring of CPU and GPU statistics.
- Automatically records data to a CSV file or MySQL database.
- Supports data visualization using `plotly`.
- Configurable monitoring intervals.

## File Directory
- `monitor.py`: Monitoring tool script.
- `requirements.txt`: Dependencies.
- `UserManual.md`: User manual.
- `Readme.md`: Project documentation.
- `test.py`: Test script for monitoring.

## Usage

### Step 1: Install dependencies in the environment (where the task will be submitted)

`pip install -r requirements.txt`

If MySQL connection-related issues arise during execution, upgrade MySQL:

``pip install --upgrade mysql-connector-python``

### Step 2: Copy the `monitor.py` script to the same directory as the task to be submitted.

### Step 3: Run the script to monitor, passing the task execution command

Note: The script needs to run on the server to be monitored. 

Note: For the metrics `cpu_power_draw` and `dram_power_draw`, they are accessed via the RAPL interface. If the values are retrieved as `N/A`, administrator permission is required to grant read access. The files that need permission modifications are as follows:  

```bash
(llama) (base) hhz@node2:~/workspace/LLM$ ls /sys/class/powercap
dtpm  intel-rapl  intel-rapl:0  intel-rapl:0:0  intel-rapl:1  intel-rapl:1:0
```  

The read permissions need to be modified for the following files: `intel-rapl:0`, `intel-rapl:0:0`, `intel-rapl:1` and `intel-rapl:1:0`.


Run the script to submit the task and start monitoring:
```bash
python monitor.py monitor -n "task_name" -t 0.5/1/3/... -cmd "Command to execute for the task" -o "csv/mysql"
```

Parameters:
- monitor: Activate monitoring function.
- n: Task name (used for identification).
- t: Sampling interval (default is 10s).
- cmd: Command to execute for the task.
- o: Storage type (default is csv).

The script will:
- Create a `monitor.log` log file in the current directory.
- Create a `task_name_timestamp.csv` file or create a table `task_name_timestamp` in the `monitor` database in MySQL (based on the `o` parameter).
- Submit the task.
- Save the real-time monitoring data to the file `task_name_timestamp.csv` or table `task_name_timestamp`.
- Automatically terminate the script and stop monitoring after the task ends.

**The file name can be found in `monitor.log`.**

Example:
```bash
python monitor.py monitor -n "fine_tuning_for_llama2_7b" -t 10 -cmd "python finetuning.py" -o "csv"
```

Parameter explanation:
- `python monitor.py monitor`: Call the `monitor.py` Python script and execute the monitoring function.
- `n "fine_tuning_for_llama2_7b"`: Specify the task name `fine_tuning_for_llama2_7b` for identification and as the name of the CSV file or database table.
- `t 10`: Set the sampling interval to 10 seconds, meaning system resource usage will be recorded every 10 seconds.
- `cmd "python finetuning.py"`: Submit and execute the command `python finetuning.py`, where `finetuning.py` is the script for fine-tuning LLaMA 2 7B.
- `o "csv"`: Store the monitoring data in a CSV file rather than in the MySQL database.

### Step 4: Generate Visualization Charts
Run the visualization function to create charts:
```bash
python monitor.py plot -t "table_name" -f "csv/mysql"
```

Parameters:
- plot: Activate the plotting function.
- t: Table name.
- f: Table format (default is csv).

This will generate an interactive chart using `plotly`, which will be displayed in the browser and saved as an `html` file in the `monitor_graphs` directory.

Two examples:
```bash
python monitor.py plot -t "fine_tunning_for_llama2_7b_20250112_202325" -f "mysql"
```

- `python monitor.py plot`: Call the `monitor.py` script and activate the plotting function.
- `t "fine_tunning_for_llama2_7b_20250112_202325"`: Specify the table name to plot data from, stored in the MySQL database, with the table name `fine_tunning_for_llama2_7b_20250112_202325`.
- `f "mysql"`: Specify the data source as MySQL.

```bash
python monitor.py plot -t "fine_tuning_for_llama2_7b_20250204_154110.csv" -f "csv"
```

- `python monitor.py plot`: Call the `monitor.py` script and activate the plotting function.
- `t "fine_tuning_for_llama2_7b_20250204_154110.csv"`: Specify the file name to plot data from, stored in the CSV file, with the file name `fine_tuning_for_llama2_7b_20250204_154110.csv`.
- `f "csv"`: Specify the data source as CSV.

## Logs
Logs are stored by default in the `monitor.log` file. Check this file for detailed information about errors and system activities.