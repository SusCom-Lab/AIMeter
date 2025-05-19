import sys
import re
import os
import glob

def extract_avg_rss(csv_path):
    if not os.path.exists(csv_path):
        print(f"文件不存在: {csv_path}")
        return None

    with open(csv_path, 'r') as f:
        rss_index = None
        total = 0.0
        count = 0

        for line in f:
            row = re.split(r'\s+', line.strip())
            if len(row) < 6:
                continue

            # 找到标题行，定位 RSS 列
            if 'RSS' in row:
                rss_index = row.index('RSS')
                continue

            # 从数据行提取 RSS 并累加（单位 KB，转换为 MB）
            if rss_index is not None and len(row) > rss_index:
                try:
                    rss_kb = float(row[rss_index])
                    rss_mb = rss_kb / 1024
                    total += rss_mb
                    count += 1
                except ValueError:
                    continue

        if count == 0:
            print(f"{csv_path} 中没有找到有效的 RSS 数据")
            return None
        else:
            avg_rss = total / count
            print(f"{csv_path} 平均 RSS 使用量: {avg_rss:.2f} MB")
            return avg_rss

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("用法: python parse_rss.py <样例文件路径，例如 llm_with_monitor_run1.csv>")
    else:
        example_path = sys.argv[1]

        if not os.path.exists(example_path):
            print(f"文件不存在: {example_path}")
            sys.exit(1)

        # 提取样本名并生成通配符路径（_runX）
        base_prefix = re.sub(r'_run\d+', '_run*', example_path)

        # 匹配所有 run 文件
        matched_files = sorted(glob.glob(base_prefix))
        if not matched_files:
            print("未找到匹配的文件")
            sys.exit(1)

        results = []
        for csv_path in matched_files:
            value = extract_avg_rss(csv_path)
            if value is not None:
                results.append(value)

        if results:
            print("所有平均 RSS (MB):", [f"{v:.2f}" for v in results])
            print(f"总平均 RSS: {sum(results)/len(results):.2f} MB")
        else:
            print("未提取到任何有效数据")
