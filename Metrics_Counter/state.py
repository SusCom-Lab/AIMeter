# 全局变量
_inserted_count = -1 # 用于记录已插入的行数
_monitor_running = False # 用于记录监控是否正在运行
_csv_file_path = "" # 用于记录CSV文件路径
_table_name = "" # 用于记录MYSQL的表格名称
_monitor_thread = None # 用于记录监控线程
_task_name = ""  # 用于记录任务名称
_sampling_interval = 10  # 采样间隔
_output_format = "csv"  # 输出格式，支持csv和mysql
_timestamp = ""  # 用于记录时间戳
_execution_times = {} # 用于保存每个函数的执行时间
_execution_times['elapsed_time'] = [] # 专门用于记录采样频率的key-value对