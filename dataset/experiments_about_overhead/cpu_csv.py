import sys
import re
import os
import glob

def extract_avg_cpu(csv_path):
    if not os.path.exists(csv_path):
        print(f"文件不存在: {csv_path}")
        return None

    with open(csv_path, 'r') as f:
        cpu_index = None
        total = 0.0
        count = 0

        for line in f:
            row = re.split(r'\s+', line.strip())
            if len(row) < 5:
                continue

            if '%CPU' in row:
                cpu_index = row.index('%CPU')
                continue

            if cpu_index is not None and len(row) > cpu_index:
                try:
                    cpu_val = float(row[cpu_index])
                    total += cpu_val
                    count += 1
                except ValueError:
                    continue

        if count == 0:
            print(f"{csv_path} 中没有找到有效的 %CPU 数据")
            return None
        else:
            avg_cpu = total / count
            print(f"{csv_path} 平均 %CPU 使用率: {avg_cpu:.2f}")
            return avg_cpu

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("用法: python parse_cpu.py <样例文件路径，例如 llm_with_monitor_run1.csv>")
    else:
        example_path = sys.argv[1]

        if not os.path.exists(example_path):
            print(f"文件不存在: {example_path}")
            sys.exit(1)

        # 替换 _runX 为 _run* 匹配所有相关文件
        base_pattern = re.sub(r'_run\d+', '_run*', example_path)
        matched_files = sorted(glob.glob(base_pattern))
        if not matched_files:
            print("未找到匹配的文件")
            sys.exit(1)

        cpu_values = []
        for path in matched_files:
            value = extract_avg_cpu(path)
            if value is not None:
                cpu_values.append(value)

        if cpu_values:
            print("所有平均 %CPU:", [f"{v:.2f}" for v in cpu_values])
            print(f"总平均 %CPU: {sum(cpu_values)/len(cpu_values):.2f}")
        else:
            print("未提取到任何有效数据")
