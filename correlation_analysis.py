import pandas as pd
import numpy as np
import re
from collections import defaultdict

# --- Pandas 显示选项设置 ---
# 设置一个足够宽的显示宽度，以便在控制台中更好地显示表格
pd.set_option('display.width', 200)
# 显示完整的列内容，不截断长字符串
pd.set_option('display.max_colwidth', None)
# 列标题左对齐
pd.set_option('display.colheader_justify', 'left')

def clean_value(value):
    """
    清洗单个数据值：
    - 如果不是字符串，则先转换为字符串（处理可能被读取为浮点数的数字）。
    - 去除首尾空格。
    - 移除常见单位（%，°C，MHz，W，GB/s）。
    - 尝试转换为浮点数，如果失败则返回 NaN。
    """
    if pd.isna(value):
        return np.nan
    value_str = str(value).strip()
    # 使用正则表达式移除末尾的单位，允许单位前有可选空格
    value_str = re.sub(r'\s*(%|°C|MHz|W|GB/s)$', '', value_str)
    try:
        return float(value_str)
    except ValueError:
        return np.nan

def get_correlation_analysis_for_group(df_group, identifier_cols):
    """
    对单个分组的 DataFrame 执行相关性分析。

    参数 (Args):
        df_group (pd.DataFrame): 特定索引分组的 DataFrame，其中潜在的指标列已被清洗。
        identifier_cols (list): 需要从相关性分析中排除的列的列表。

    返回 (Returns):
        元组 (tuple): (相关性矩阵, 排序后的相关性对) 或者 (None, None) 如果无法进行分析。
    """
    # 选择数值类型的列
    numeric_cols = df_group.select_dtypes(include=np.number).columns
    # 排除标识列，得到用于相关性分析的列
    cols_to_correlate = [col for col in numeric_cols if col not in identifier_cols]

    # 检查是否有足够的列进行分析
    if len(cols_to_correlate) < 2:
        print(f"分组中没有足够的数值列（至少需要2列，实际找到 {len(cols_to_correlate)} 列）进行相关性分析。")
        return None, None

    data_for_correlation = df_group[cols_to_correlate]

    # 检查是否有足够的数据行进行分析
    if data_for_correlation.shape[0] < 2:
        print("分组中没有足够的数据行（至少需要2行）进行相关性分析。")
        return None, None

    # 移除没有方差（所有值都相同）的列
    data_for_correlation = data_for_correlation.loc[:, data_for_correlation.nunique() > 1]
    # 再次检查是否有足够的列
    if data_for_correlation.shape[1] < 2:
        print(f"分组中没有足够的具有方差的数值列（至少需要2列）进行相关性分析。")
        return None, None

    # 计算皮尔逊相关性矩阵
    correlation_matrix = data_for_correlation.corr(method='pearson')

    # 创建上三角掩码（不包括对角线 k=1）
    mask = np.triu(np.ones_like(correlation_matrix, dtype=bool), k=1)
    # 提取上三角部分的相关系数
    upper_triangle = correlation_matrix.where(mask)
    # 将上三角矩阵转换为 Series，并按相关系数降序排序
    sorted_pairs = upper_triangle.stack().sort_values(ascending=False).rename("correlation_coefficient")

    return correlation_matrix, sorted_pairs

class CsvCorrelationAnalyzer:
    def __init__(self, csv_filepath):
        self.filepath = csv_filepath
        self.df_original = None
        self.df_processed_groups = {}
        self.results_by_index_group = defaultdict(dict)
        # 定义不参与相关性计算的标识列
        self.identifier_cols = ['timestamp', 'task_name', 'name', 'index']

        try:
            self.df_original = pd.read_csv(self.filepath)
            self._preprocess_data()
        except FileNotFoundError:
            print(f"错误：在路径 {self.filepath} 未找到 CSV 文件")
            # 初始化为空 DataFrame，以便后续检查 .empty
            self.df_original = pd.DataFrame()
        except Exception as e:
            print(f"加载或预处理 CSV 时出错: {e}")
            self.df_original = pd.DataFrame()

    def _preprocess_data(self):
        """预处理数据：清洗数值列并按 'index' 分组。"""
        if self.df_original is None or self.df_original.empty:
            return

        df_copy = self.df_original.copy()
        # 识别潜在的需要清洗的指标列
        potential_metric_cols = [col for col in df_copy.columns if col not in self.identifier_cols]

        # 清洗并转换指标列为数值类型
        for col in potential_metric_cols:
            df_copy[col] = df_copy[col].apply(clean_value)
            # 再次尝试转换为数值，确保 apply 返回的是数字
            df_copy[col] = pd.to_numeric(df_copy[col], errors='coerce') # errors='coerce' 会将无法转换的值设为 NaN

        # 确保 'index' 列存在且为字符串类型，以便正确分组
        if 'index' in df_copy.columns:
            df_copy['index'] = df_copy['index'].astype(str)
            # 按 'index' 列分组，并将结果存储在字典中
            self.df_processed_groups = {
                str(idx_val): group_df
                for idx_val, group_df in df_copy.groupby('index')
            }
            if not self.df_processed_groups:
                 print("警告：尝试按 'index' 列分组后未找到任何组。请检查 'index' 列的内容和类型。")
        else:
            print("警告：CSV文件中未找到 'index' 列，无法进行分组分析。")
            self.df_processed_groups = {} # 明确设为空字典


    def analyze_all_groups(self, top_n=10):
        """对所有分组执行相关性分析并打印结果。"""
        if not self.df_processed_groups:
            print("没有已处理的数据分组可供分析。请检查 CSV 加载和 'index' 列。")
            return

        print(f"\n找到以下 'index' 值的组： {list(self.df_processed_groups.keys())}")
        print("=" * 60) # 稍微加宽分隔线

        for index_val, group_df in self.df_processed_groups.items():
            print(f"\n--- 正在分析索引分组: {index_val} ---")
            if group_df.empty:
                print("分组为空，跳过。")
                continue

            # 获取相关性分析结果
            correlation_matrix, sorted_pairs = get_correlation_analysis_for_group(group_df, self.identifier_cols)

            # 存储结果
            self.results_by_index_group[index_val]['matrix'] = correlation_matrix
            self.results_by_index_group[index_val]['pairs'] = sorted_pairs

            # 打印结果
            if correlation_matrix is not None:
                print("\n相关性矩阵:")
                # 使用 to_string() 并传递参数以确保格式化应用
                print(correlation_matrix.to_string(float_format="{:.4f}".format)) # 格式化矩阵中的浮点数

                if sorted_pairs is not None and not sorted_pairs.empty:
                    float_formatter = "{:.6f}".format  # 格式化浮点数以显示6位小数

                    print(f"\n前 {top_n} 个正相关性最强的指标对：")
                    top_positive_pairs = sorted_pairs.head(top_n)
                    if not top_positive_pairs.empty:
                        df_top_positive = top_positive_pairs.reset_index()
                        # 重命名列以便更清晰地显示
                        df_top_positive.columns = ['指标 A', '指标 B', '相关系数']
                        # 使用 to_string 输出，不显示索引和表头，左对齐，并应用格式化
                        print(df_top_positive.to_string(index=False,
                                                        header=True, # 显示列名更清晰
                                                        justify='left',
                                                        formatters={'相关系数': float_formatter}))
                    else:
                        print("此分组中未找到正相关性对。")

                    print(f"\n前 {top_n} 个负相关性最强的指标对（最负相关的）：")
                    # 先取尾部，再升序排序得到最负相关的
                    top_negative_pairs = sorted_pairs.tail(top_n).sort_values(ascending=True)
                    if not top_negative_pairs.empty:
                        df_top_negative = top_negative_pairs.reset_index()
                        df_top_negative.columns = ['指标 A', '指标 B', '相关系数']
                        print(df_top_negative.to_string(index=False,
                                                        header=True, # 显示列名
                                                        justify='left',
                                                        formatters={'相关系数': float_formatter}))
                    else:
                        print("此分组中未找到负相关性对。")
                else:
                    print("此分组未找到相关性对（可能所有数值列都无方差或只有一列）。")
            else:
                # 如果 get_correlation_analysis_for_group 返回 None, None，相关消息已在函数内打印
                # 此处可以补充或保持安静
                pass # 消息已在 get_correlation_analysis_for_group 中打印

            print("-" * 60) # 分隔线与上面的等号线匹配

    def get_specific_correlation(self, index_val_str, metric1, metric2):
        """获取指定分组中特定两个指标之间的相关系数。"""
        index_val_str = str(index_val_str) # 确保输入是字符串
        if index_val_str not in self.results_by_index_group:
            print(f"错误：索引分组 '{index_val_str}' 无分析结果。可用分组: {list(self.results_by_index_group.keys())}")
            return None

        matrix = self.results_by_index_group[index_val_str].get('matrix')
        if matrix is None:
            print(f"错误：索引分组 '{index_val_str}' 的相关性矩阵不可用（可能分析失败）。")
            return None

        # 检查两个指标是否存在于该分组的相关性矩阵的列和索引中
        if metric1 not in matrix.columns or metric2 not in matrix.columns:
            print(f"错误：指标 '{metric1}' 或 '{metric2}' 在分组 '{index_val_str}' 的相关性矩阵中未找到。")
            print(f"该分组可用指标: {matrix.columns.tolist()}")
            return None

        # 使用 .loc 获取相关系数
        return matrix.loc[metric1, metric2]

# --- 示例用法 ---
if __name__ == "__main__":
    # 确保路径正确
    your_csv_file_path = '/home/ldaphome/hhz/workspace/LLM/experiment_files/A800_Llama2-7b_prefill_decode_batch_size_2_input_40000_0.1.csv'
    print(f"尝试从以下路径加载 CSV 文件: {your_csv_file_path}")

    analyzer = CsvCorrelationAnalyzer(csv_filepath=your_csv_file_path)

    # 只有在成功加载并处理数据后才进行分析
    if analyzer.df_original is not None and not analyzer.df_original.empty and analyzer.df_processed_groups:
        # analyze_all_groups 会自动检测所有分组并输出它们的完整分析结果
        analyzer.analyze_all_groups(top_n=6) # 指定显示前 6 个

        # # --- 演示如何查询特定指标对的相关性 ---
        # print("\n" + "=" * 60)
        # print("--- 针对所有分组的特定相关性查询示例 ---")
        # print("=" * 60)

        # available_groups = list(analyzer.results_by_index_group.keys())

        # if available_groups:
        #     print(f"可用的分析分组索引: {available_groups}")

        #     # 定义一些您可能感兴趣的指标对
        #     metric_pairs_to_check = [
        #         ('power.draw [W]', 'temperature.gpu'),
        #         ('utilization.gpu [%]', 'sm_active.%'), # 假设sm_active列名是 'sm_active.%'
        #         ('dram_active', 'fb_used'),             # 假设列名为 'dram_active' 和 'fb_used'
        #         # ('dram_usage', 'usage.memory [%]') # 原始示例中的对
        #         # 您可以根据实际的列名添加更多指标对
        #     ]

        #     for group_idx in available_groups: # 遍历所有检测到的分组
        #         print(f"\n--- 正在查询分组: {group_idx} ---")
        #         for metric1, metric2 in metric_pairs_to_check:
        #             print(f"查询 '{metric1}' 与 '{metric2}' 的相关性:")
        #             # get_specific_correlation 内部会检查指标是否存在并打印错误（如果需要）
        #             coeff = analyzer.get_specific_correlation(group_idx, metric1, metric2)
        #             # 只有在成功获取系数时才打印结果
        #             if coeff is not None:
        #                 print(f"  -> 相关系数: {coeff:.6f}")
        #             # else: # 错误消息已在 get_specific_correlation 中处理

        # else:
        #     print("未找到任何可进行特定相关性查询的分组。")
    else:
        print("加载或处理 CSV 失败，或未能成功分组。分析无法继续。")