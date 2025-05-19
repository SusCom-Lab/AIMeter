from config import Config
import mysql.connector
import csv
import os
import state
import re
from resources_consumption_record import timing_decorator
import mysql.connector
import hashlib

def sanitize_metric_key(key: str) -> str:
    """将指标名转换为更安全的 SQL 列名。"""
    if not isinstance(key, str):
        key = str(key)
    # 将非字母数字字符（包括点、括号、百分号等）替换为下划线
    sanitized = re.sub(r'[^\w]+', '_', key)
    # 去除开头和结尾的下划线
    sanitized = sanitized.strip('_')
    # 如果开头是数字，则在前面加一个下划线
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    # 可选：截断长度以避免超过 MySQL 列名限制（如 64 字符）
    sanitized = sanitized[:60]
    if not sanitized:
        # 如果清洗后为空，则使用哈希作为兜底方案
        sanitized = 'metric_' + hashlib.md5(key.encode()).hexdigest()[:10]
    return sanitized

def get_existing_columns(cursor, table_name: str) -> set[str]:
    """获取某个表中已存在的列名集合。"""
    try:
        # 使用 INFORMATION_SCHEMA 提供更广泛兼容性
        cursor.execute(f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = '{table_name}'
        """)
        # 另一种方式：cursor.execute(f"DESCRIBE `{table_name}`")
        return {row[0] for row in cursor.fetchall()}
    except mysql.connector.Error as e:
        # 处理表可能真的不存在的情况（即使 SHOW TABLES 显示它存在）
        if e.errno == 1146:  # 表不存在的错误码 ER_NO_SUCH_TABLE
            return set()
        print(f"警告：无法获取表 `{table_name}` 的列信息: {e}")
        return set()  # 出错时返回空集合

def save_to_mysql(task_name: str, metrics: dict[str, any], table_timestamp: str, insert_timestamp: str) -> None:
    """
    将监控 metrics 写入 MySQL，动态创建/修改表结构以匹配 metrics 中的键。
    警告：频繁的 ALTER TABLE 可能影响性能。建议在非生产环境或低频监控中使用。
    参数:
    - task_name: 任务名称
    - metrics: 包含所有监控指标的字典
    - table_timestamp: 用于生成表名的时间戳字符串
    - insert_timestamp: 用于记录每行数据时间戳的字符串
    """
    # 安全处理任务名以生成合法表名
    safe_task_name = "".join(c if c.isalnum() else "_" for c in task_name)
    state._table_name = f"{safe_task_name}_{table_timestamp}"

    mydb = None
    cursor = None
    new_columns_added = False

    try:
        # 连接数据库
        mydb = mysql.connector.connect(
            host=Config.host, 
            user=Config.user,
            password=Config.password, 
            database=Config.database
        )
        cursor = mydb.cursor()

        # 1. 收集所有可能的列名（包括基础字段和 gpu_info 中的字段）
        all_metric_keys = set()
        base_keys = set(k for k in metrics if k != 'gpu_info')
        all_metric_keys.update(base_keys)
        gpu_info_list = metrics.get('gpu_info', [])
        for gpu_data in gpu_info_list:
            all_metric_keys.update(gpu_data.keys())

        # 定义静态字段
        static_columns = {'id', 'timestamp', 'task_name'}
        # 将字段名进行清洗（去除特殊字符）
        potential_dynamic_columns = {sanitize_metric_key(k): k for k in all_metric_keys}
        all_potential_columns = static_columns.union(potential_dynamic_columns.keys())

        # 2. 检查表是否存在，并获取其列名
        cursor.execute(f"SHOW TABLES LIKE '{state._table_name}'")
        table_exists = cursor.fetchone() is not None

        existing_columns = set()
        if table_exists:
            # 表存在则获取已有列
            existing_columns = get_existing_columns(cursor, state._table_name)
            if not existing_columns and table_exists:
                print(f"错误：表 `{state._table_name}` 存在但无法获取列信息。终止写入。")
                return

            # 3. 如果有缺失列则进行 ALTER TABLE
            columns_to_add = {
                col for col in all_potential_columns
                if col not in existing_columns and col not in static_columns
            }
            if columns_to_add:
                print(f"检测到字段漂移：将添加新列至 `{state._table_name}`：{', '.join(columns_to_add)}")
                for col_name in columns_to_add:
                    col_type = "VARCHAR(255) NULL DEFAULT NULL"
                    try:
                        alter_query = f"ALTER TABLE `{state._table_name}` ADD COLUMN `{col_name}` {col_type}"
                        print(f"执行 SQL: {alter_query}")
                        cursor.execute(alter_query)
                        new_columns_added = True
                    except mysql.connector.Error as e:
                        print(f"警告：添加列 `{col_name}` 到表 `{state._table_name}` 失败：{e}")
                mydb.commit()
        else:
            # 4. 如果表不存在则创建新表
            # print(f"创建新表：`{state._table_name}`")
            columns_definitions = [
                "id INT AUTO_INCREMENT PRIMARY KEY",
                "timestamp DATETIME COMMENT '数据插入时间'",
                "task_name VARCHAR(255) COMMENT '任务名称'"
            ]
            for col_name in sorted(list(potential_dynamic_columns.keys())):
                col_type = "VARCHAR(255) NULL DEFAULT NULL"
                columns_definitions.append(f"`{col_name}` {col_type}")

            # 添加索引
            columns_definitions.extend([
                "INDEX(timestamp)", "INDEX(task_name)",
                f"INDEX(`{sanitize_metric_key('index')}`)" if sanitize_metric_key('index') in potential_dynamic_columns else ""
            ])
            columns_definitions = [c for c in columns_definitions if c]

            create_query = f"""
                CREATE TABLE `{state._table_name}` (
                    {', '.join(columns_definitions)}
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
            cursor.execute(create_query)
            mydb.commit()

        # 5. 获取最终列名用于插入数据（确保最新结构）
        final_columns_in_db = sorted(list(get_existing_columns(cursor, state._table_name)))
        if 'id' in final_columns_in_db:
            final_columns_in_db.remove('id')

        if not final_columns_in_db:
            print(f"错误：表 `{state._table_name}` 的最终列无法确定。")
            return

        # 6. 准备插入的数据行
        base_fields = {k: metrics.get(k) for k in metrics if k != 'gpu_info'}
        rows_to_insert = []

        if not gpu_info_list and not base_fields:
            print("警告：未找到任何基础指标或 GPU 信息，不执行插入。")
            return

        effective_gpu_list = gpu_info_list if gpu_info_list else [{}]

        for gpu_data in effective_gpu_list:
            data_for_row = {
                'timestamp': insert_timestamp,
                'task_name': task_name
            }
            for original_key, value in base_fields.items():
                sanitized_key = sanitize_metric_key(original_key)
                data_for_row[sanitized_key] = value
            for original_key, value in gpu_data.items():
                sanitized_key = sanitize_metric_key(original_key)
                data_for_row[sanitized_key] = value

            # 按列顺序构造数据元组
            data_tuple = []
            for col_name in final_columns_in_db:
                value = data_for_row.get(col_name, None)
                if col_name == 'gpu_index' and value is not None:
                    try: value = int(value)
                    except (ValueError, TypeError): value = None
                data_tuple.append(value)

            rows_to_insert.append(tuple(data_tuple))

        # 7. 执行批量插入
        if rows_to_insert:
            column_str = ", ".join([f"`{col}`" for col in final_columns_in_db])
            placeholder_str = ", ".join(["%s"] * len(final_columns_in_db))
            insert_query = f"INSERT INTO `{state._table_name}` ({column_str}) VALUES ({placeholder_str})"
            cursor.executemany(insert_query, rows_to_insert)
            mydb.commit()

            # 记录插入计数
            if state._inserted_count == -1:
                state._inserted_count = 0
            state._inserted_count += len(rows_to_insert)

    except mysql.connector.Error as e:
        print(f"MySQL 错误：动态写入表 `{state._table_name}` 时发生错误：{e}")
        if mydb and mydb.is_connected():
            try: mydb.rollback()
            except Exception as rb_e:
                print(f"回滚失败：{rb_e}")
    except Exception as e:
        print(f"未预料的错误：写入表 `{state._table_name}` 时出现异常：{e}")
    finally:
        if cursor: cursor.close()
        if mydb and mydb.is_connected(): mydb.close()

def save_to_csv(task_name: str, metrics: dict[str, any], file_timestamp: str, insert_timestamp: str) -> None:
    """
    将监控 metrics 动态写入 CSV。
    参数:
    - task_name: 任务名称，用于文件名和记录
    - metrics: 各项监控指标，结构示例：
        {
            'cpu_usage': '2.2 %',
            'cpu_power': 'N/A',
            'dram_usage': '23.7 %',
            'dram_power': 'N/A',
            'gpu_info': [
                {'index': '0', 'name': 'NVIDIA...', 'utilization.gpu [%]': '100 %', 'temperature.gpu': '80', 'temperature.memory': '85', ...},
                {...}
            ]
        }
    - file_timestamp: 用于生成文件名的时间戳字符串
    - insert_timestamp: 用于记录每行 timestamp 字段
    """
    # 构建文件名和写入模式
    filename = f"{task_name}_{file_timestamp}.csv"
    is_new = not os.path.exists(filename)
    mode = 'w' if is_new else 'a'
    state._csv_file_path = os.path.abspath(filename)
    # 准备多行数据，每个 GPU 一行
    rows = []
    # 基础字段来自 metrics 中除 gpu_info 外的所有键
    base_fields = {k: metrics.get(k, 'N/A')
                   for k in metrics.keys() if k != 'gpu_info'}
    rows_data = metrics.get('gpu_info', [{}])
    for gpu in rows_data:
        # 复制并格式化 GPU 字段值（给温度字段加单位）
        formatted_gpu = {}
        for k, v in gpu.items():
            if 'temperature' in k and v not in (None, 'N/A'):
                formatted_gpu[k] = f"{v}"
            else:
                formatted_gpu[k] = v
        # 合并行数据
        row = {
            'timestamp': insert_timestamp,
            'task_name': task_name,
            **base_fields,
            **formatted_gpu
        }
        rows.append(row)
    # 动态确定所有列的顺序：保证 timestamp, task_name 固定在前
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    sorted_keys = ['timestamp', 'task_name', 'name', 'index'] + [k for k in all_keys if k not in ('timestamp', 'task_name', 'name', 'index')]
    try:
        with open(filename, mode=mode, newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=sorted_keys)
            if is_new:
                writer.writeheader()
                # 初始计数
                if state._inserted_count < 0:
                    state._inserted_count = 0
            # 写入所有行
            for row in rows:
                writer.writerow(row)
            # 更新计数
            state._inserted_count += len(rows)
    except PermissionError as pe:
        print(f"Permission denied for file {filename}: {pe}")
    except csv.Error as ce:
        print(f"CSV formatting error: {ce}")
    except Exception as e:
        print(f"Unexpected error in save_to_csv: {e}")
