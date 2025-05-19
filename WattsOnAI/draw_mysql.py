import pandas as pd
import dash
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import re
import socket
import requests
from plotly.colors import qualitative
import mysql.connector # Use mysql.connector directly
from mysql.connector import Error # For error handling
import os # Optional: To read credentials from environment variables
from config import Config # Assuming you have a config.py with your DB credentials

# --- Database Connection (Using mysql.connector) ---
def create_db_connection(db_config):
    """Establishes a connection to the MySQL database using mysql-connector-python."""
    connection = None
    try:
        connection = mysql.connector.connect(
            host=db_config['host'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database']
        )
        if connection.is_connected():
            print("Successfully connected to MySQL database using mysql.connector.")
            return connection
        else:
            print("Failed to connect to MySQL database.")
            raise RuntimeError("Database connection failed (connector)")
    except Error as e:
        print(f"Error connecting to MySQL database using mysql.connector: {e}")
        raise RuntimeError("Database connection failed (connector)") from e
    except KeyError as e:
        print(f"Missing database configuration key: {e}")
        raise RuntimeError("Invalid database configuration") from e

# --- Port Finding (Unchanged) ---
def find_available_port(start=8050, end=8100):
    """查找一个可用的端口"""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有找到可用端口，请检查端口占用情况")

# --- Unit Stripping (Unchanged, handles new units/N/A correctly) ---
def strip_unit(val):
    """提取数值部分 (Handles 'N/A' -> None)"""
    if pd.isnull(val) or val == 'N/A': # Explicitly handle N/A
        return None
    # Regex finds the first number (int/float, optional sign)
    match = re.search(r"[-+]?\d*\.?\d+", str(val))
    return float(match.group()) if match else None

# --- Unit Cleaning (Unchanged logic, field names updated later) ---
def clean_units(df: pd.DataFrame, unit_fields: list[str]):
    """剥离单位并保留原值供 hover 使用"""
    cleaned_columns = []
    for field in unit_fields:
        if field in df.columns:
            raw_col_name = f'{field}_raw'
            df[raw_col_name] = df[field]  # 保存原值用于 hover 显示
            df[field] = df[field].apply(strip_unit)
            # Attempt to convert to numeric after stripping, handling potential errors
            df[field] = pd.to_numeric(df[field], errors='coerce')
            cleaned_columns.append(field)
        # else:
        #     print(f"Warning: Field '{field}' not found in DataFrame, skipping cleaning.")
    # print(f"Cleaned numeric columns: {cleaned_columns}")
    return df

# --- Dashboard Creation (Unchanged from previous MySQL version) ---
def create_dashboard(df: pd.DataFrame):
    """Creates the Dash application instance."""

    # --- Define Categories using ACTUAL DataFrame column names ---
    available_cols = set(df.columns)
    potential_categories = {
        "Energy Section": ['power_draw_W', 'temperature_gpu', 'temperature_memory', 'cpu_power', 'dram_power'],
        "Compute Section": [
            'utilization_gpu', 'clocks_current_graphics_MHz',
            'clocks_current_sm_MHz', 'sm_active', 'sm_occupancy',
            'tensor_active', 'fp64_active', 'fp32_active', 'fp16_active'
        ],
        "MemorySection": [
            'utilization_memory', 'clocks_current_memory_MHz',
            'usage_memory'
        ],
        "Communication Section": [
            'pcie_link_gen_current', 'pcie_link_width_current',
            'pcie_tx_bytes', 'pcie_rx_bytes', 'nvlink_tx_bytes', 'nvlink_rx_bytes'
        ],
        "System Section": ['cpu_usage', 'dram_active', 'dram_usage']
    }
    categories = {}
    all_metrics_in_categories = []
    for cat, metrics in potential_categories.items():
        valid_metrics = [m for m in metrics if m in available_cols]
        if valid_metrics:
            categories[cat] = valid_metrics
            all_metrics_in_categories.extend(valid_metrics)

    # --- Create Dash App ---
    app = Dash(__name__)
    app.layout = html.Div([
        html.H2("GPU & 系统指标可视化 (MySQL - mysql.connector)", style={'textAlign': 'center'}), # Updated title slightly

        # --- Controls: X-Axis and GPU Select ---
        html.Div([
            html.Div([
                html.Label("横坐标：", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='x-axis',
                    options=[{'label': '时间戳', 'value': 'timestamp'}],
                    value='timestamp',
                    clearable=False
                )
            ], style={'width': '20%', 'display': 'inline-block', 'padding': '10px'}),

            html.Div([
                html.Label("选择 GPU：", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='gpu-select',
                    options=[{'label': f"GPU {i}", 'value': i} for i in sorted(df['index'].unique())] if 'index' in df else [],
                    value=sorted(df['index'].unique()) if 'index' in df else [],
                    multi=True
                )
            ], style={'width': '35%', 'display': 'inline-block', 'padding': '10px'}),
        ], style={'display': 'flex', 'justifyContent': 'center'}),

        # --- Controls: Metric Select (Categorized) ---
        html.Div([
            *[
                html.Div([
                    html.Label(cat, style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id={'type': 'cat-select', 'index': cat},
                        options=[{'label': m, 'value': m} for m in metrics],
                        multi=True,
                        placeholder='请选择...'
                    )
                ], style={
                    'width': '19%', 'margin': '10px', 'padding': '10px',
                    'backgroundColor': '#f7f7f7',
                    'borderRadius': '8px'
                }) for cat, metrics in categories.items()
            ]
        ], style={
            'display': 'flex',
            'flexWrap': 'wrap',
            'justifyContent': 'center',
            'gap': '15px',
            'padding': '15px',
            'boxShadow': '0 4px 8px rgba(0, 0, 0, 0.1)',
            'borderRadius': '10px',
            'backgroundColor': '#ffffff',
            'margin': '15px auto',
            'width': '95%'
        }),

        # --- Graph Area ---
        dcc.Graph(id='indicator-graph', style={'height': '70vh', 'marginTop': '20px'})

    ], style={'fontFamily': 'Arial, sans-serif', 'margin': '0 auto', 'width': '95%'})


    # --- Callback (Unchanged logic) ---
    @app.callback(
        Output('indicator-graph', 'figure'),
        Input('x-axis', 'value'),
        Input('gpu-select', 'value'),
        Input({'type': 'cat-select', 'index': dash.ALL}, 'value')
    )
    def update_graph(x_axis, selected_gpus, selections):
        if not selected_gpus or not x_axis or x_axis not in df.columns:
            raise PreventUpdate

        metrics_selected = [m for sel in selections if sel for m in sel]
        if not metrics_selected:
            raise PreventUpdate

        dff = df[df['index'].isin(selected_gpus)]

        palette = qualitative.Plotly
        color_map = { gpu: palette[i % len(palette)]
                      for i, gpu in enumerate(sorted(selected_gpus)) }
        dash_styles = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot']
        symbol_list = ['circle', 'square', 'diamond', 'cross', 'x',
                       'triangle-up', 'triangle-down', 'pentagon', 'hexagon']
        dash_map = { metric: dash_styles[i % len(dash_styles)]
                     for i, metric in enumerate(metrics_selected) }
        symbol_map = { metric: symbol_list[i % len(symbol_list)]
                       for i, metric in enumerate(metrics_selected) }

        fig = go.Figure()
        for gpu in selected_gpus:
            dfg = dff[dff['index'] == gpu]
            if dfg.empty:
                continue

            for metric in metrics_selected:
                if metric in dfg.columns and not dfg[metric].isnull().all():
                    raw_col = f"{metric}_raw"
                    hover_texts = [
                        f"时间: {t.strftime('%Y-%m-%d %H:%M:%S')}<br>GPU: {gpu}<br>{metric}: {dfg[raw_col].iloc[i] if raw_col in dfg else val}"
                        for i, (t, val) in enumerate(zip(dfg[x_axis], dfg[metric]))
                        if pd.notnull(t)
                    ]
                    if not hover_texts:
                         hover_texts = None

                    fig.add_trace(go.Scatter(
                        x=dfg[x_axis],
                        y=dfg[metric],
                        mode='lines+markers',
                        name=f"GPU{gpu} — {metric}",
                        legendgroup=f"GPU{gpu}",
                        line=dict(
                            color=color_map.get(gpu),
                            dash=dash_map.get(metric),
                            shape='linear'
                        ),
                        marker=dict(
                            symbol=symbol_map.get(metric),
                            size=6
                        ),
                        hoverinfo='text',
                        hovertext=hover_texts
                    ))

        fig.update_layout(
            title="指标趋势",
            xaxis=dict(
                title="时间",
                tickformat="%Y-%m-%d %H:%M:%S",
                tickangle=-30,
                showgrid=True,
                gridcolor='#e0e0e0'
            ),
            yaxis=dict(
                title="数值",
                showgrid=True,
                gridcolor='#e0e0e0',
            ),
            legend_title="图例",
            margin=dict(l=50, r=50, t=80, b=80),
            plot_bgcolor='white',
            paper_bgcolor='white',
            hovermode='x unified'
        )
        return fig

    return app

def get_server_ip():
    try:
        # 优先尝试获取公网 IP（如已连接外网）
        return requests.get("https://api.ipify.org").text
    except:
        # 退而求其次获取本地网卡 IP（适用于局域网或内网）
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)

# --- Main Function to Run from MySQL (Using mysql.connector) ---
def draw_from_mysql(db_config: dict, table_name: str):
    """Loads data from MySQL using mysql.connector, cleans it, and runs the Dash app."""

    connection = None # Initialize connection to None
    try:
        # --- 1. Connect and Fetch Data ---
        connection = create_db_connection(db_config) # Get connection object
        query = f"SELECT * FROM `{table_name}` ORDER BY timestamp ASC"
        print(f"Executing query: {query}")

        # pd.read_sql_query works with DBAPI2 connections like mysql.connector's
        df = pd.read_sql_query(query, connection)
        print(f"Successfully loaded {len(df)} rows from table '{table_name}'.")

        # Manually parse timestamp column as pandas might not do it automatically with mysql.connector
        if 'timestamp' in df.columns:
             df['timestamp'] = pd.to_datetime(df['timestamp'])
             print("Parsed 'timestamp' column to datetime objects.")
        else:
             print("Warning: 'timestamp' column not found for parsing.")


    except Exception as e:
        print(f"Error during database operation or data loading: {e}")
        raise RuntimeError("Failed to load data from MySQL") from e
    finally:
        # --- Ensure connection is closed ---
        if connection and connection.is_connected():
            connection.close()
            print("MySQL connection closed.")

    if df.empty:
        print(f"Warning: No data found in table '{table_name}'. Exiting.")
        return

    # --- 2. Clean 'index' (GPU ID) column (Unchanged) ---
    if 'index' in df.columns:
        df['index'] = pd.to_numeric(df['index'], errors='coerce')
        df = df.dropna(subset=['index'])
        df['index'] = df['index'].astype(int)
    else:
        print("Warning: 'index' column not found. GPU selection might not work.")

    # --- 3. Define fields requiring unit stripping (Unchanged) ---
    unit_fields = [
        'clocks_current_graphics_MHz', 'clocks_current_memory_MHz',
        'clocks_current_sm_MHz', 'power_draw_W', 'utilization_gpu',
        'utilization_memory', 'cpu_power', 'cpu_usage', 'dram_power',
        'dram_usage', 'dram_active', 'memory_copy_util',
        'nvlink_rx_bytes', 'nvlink_tx_bytes', 'pcie_rx_bytes',
        'pcie_tx_bytes', 'sm_active', 'sm_occupancy', 'tensor_active', 'usage_memory',
        'fp16_active', 'fp32_active', 'fp64_active'
    ]

    # --- 4. Clean Units (Unchanged) ---
    df = clean_units(df, unit_fields)

    # --- 5. Create and Run Dashboard (Unchanged) ---
    app = create_dashboard(df)
    port = find_available_port()
    ip = get_server_ip()

    print(f"Dash 应用运行在 http://{ip}:{port}")
    app.run(debug=True, port=port, host='0.0.0.0')