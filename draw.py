import pandas as pd
import dash
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import re
import socket
import socket
import requests
from plotly.colors import qualitative
from dash import Dash, html, dcc, Input, Output,  ALL

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

def strip_unit(val):
    """提取数值部分"""
    if pd.isnull(val):
        return None
    match = re.search(r"[-+]?\d*\.?\d+", str(val))
    return float(match.group()) if match else None



def clean_units(df: pd.DataFrame, unit_fields: list[str]):
    """剥离单位并保留原值供 hover 使用"""
    for field in unit_fields:
        if field in df.columns:
            df[f'{field}_raw'] = df[field]  # 保存原值用于 hover 显示
            df[field] = df[field].apply(strip_unit)
    return df
    
def create_dashboard(df: pd.DataFrame):
    categories = {
        "Energy Section": ['power.draw [W]', 'temperature.gpu', 'cpu_power', 'dram_power'],
        "Compute Section": [
            'utilization.gpu [%]', 'clocks.current.graphics [MHz]',
            'clocks.current.sm [MHz]', 'sm_active', 'sm_occupancy',
            'tensor_active', 'fp64_active', 'fp32_active', 'fp16_active'
        ],
        "Memory Section": [
            'utilization.memory [%]', 'temperature.memory',
            'clocks.current.memory [MHz]', 'usage.memory [%]','dram_active',
        ],
        "Communication Section": [
            'pcie.link.gen.current', 'pcie.link.width.current',
            'pcie_tx_bytes', 'pcie_rx_bytes', 'nvlink_tx_bytes', 'nvlink_rx_bytes'
        ],
        "System Section": ['cpu_usage','dram_usage']
    }

    app = Dash(__name__)
    app.layout = html.Div([
        html.H2("GPU & SYSTEM METRICS VISULIZATION", style={'textAlign': 'center'}),
        
        html.Div([
            html.Div([
                html.Label("X-axis：", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='x-axis',
                    options=[{'label': 'Timestamp', 'value': 'timestamp'}],
                    value='timestamp',
                    clearable=False
                )
            ], style={'width': '20%', 'display': 'inline-block', 'padding': '10px'}),

            html.Div([
                html.Label("Choose GPU：", style={'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='gpu-select',
                    options=[{'label': f"GPU {i}", 'value': i} for i in sorted(df['index'].unique())],
                    value=sorted(df['index'].unique()),
                    multi=True
                )
            ], style={'width': '35%', 'display': 'inline-block', 'padding': '10px'}),
        ], style={'display': 'flex', 'justifyContent': 'center'}),

        html.Div([
            *[
                html.Div([
                    html.Label(cat, style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id={'type': 'cat-select', 'index': cat},
                        options=[{'label': m, 'value': m} for m in metrics],
                        multi=True,
                        placeholder='To select...'
                    )
                ], style={
                    'width': '19%', 'margin': '10px', 'padding': '10px',
                    'backgroundColor': '#f7f7f7',
                    'borderRadius': '8px'
                }) for cat, metrics in categories.items()
            ]
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'gap': '20px',
            'padding': '15px',
            'boxShadow': '0 4px 8px rgba(0, 0, 0, 0.1)',
            'borderRadius': '10px',
            'backgroundColor': '#f7f7f7',
            'margin': '0 auto',
            'width': '95%'
        }),

        dcc.Graph(id='indicator-graph', style={'height': '70vh', 'marginTop': '20px'})
    ], style={'fontFamily': 'Arial, sans-serif', 'margin': '0 auto', 'width': '95%'})
    
    @app.callback(
    Output('indicator-graph', 'figure'),
    Input('x-axis', 'value'),
    Input('gpu-select', 'value'),
    Input({'type': 'cat-select', 'index': dash.ALL}, 'value')
    )
    def update_graph(x_axis, selected_gpus, selections):
        if not selected_gpus:
            raise PreventUpdate
        metrics_selected = [m for sel in selections for m in (sel or [])]
        if not metrics_selected:
            raise PreventUpdate

        # 生成映射：指标 → 颜色
        palette = qualitative.Plotly
        color_map = { metric: palette[i % len(palette)]
                    for i, metric in enumerate(metrics_selected) }

        # 生成映射：GPU → 点形状
        symbol_list = ['circle', 'square', 'diamond', 'cross', 'x',
                      'triangle-up', 'triangle-down', 'pentagon', 'hexagon']
        symbol_map = { gpu: symbol_list[i % len(symbol_list)]
                     for i, gpu in enumerate(sorted(selected_gpus)) }

        # 线型样式（保持相同）
        dash_styles = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot']
        
        fig = go.Figure()
        for gpu in selected_gpus:
            dfg = df[df['index'] == gpu]
            for metric in metrics_selected:
                if metric in dfg.columns:
                    raw_col = f"{metric}_raw" if f"{metric}_raw" in dfg.columns else None
                    hover_text = [
                        f"Timestamp: {t.strftime('%H:%M:%S')}.{int(t.microsecond / 100000)}<br>{metric}: {dfg[raw_col].iloc[i] if raw_col else val}"
                        for i, (t, val) in enumerate(zip(dfg[x_axis], dfg[metric]))
                    ]
                    fig.add_trace(go.Scatter(
                        x=dfg[x_axis],
                        y=dfg[metric],
                        mode='lines+markers',
                        name=f"GPU{gpu} — {metric}",
                        legendgroup=f"GPU{gpu}",
                        line=dict(
                            color=color_map[metric],  # 指标决定颜色
                            dash=dash_styles[gpu % len(dash_styles)],  # GPU决定线型
                            shape='linear'
                            # width=5
                        ),
                        marker=dict(
                            symbol=symbol_map[gpu],  # GPU决定点形状
                            size=6,
                            color=color_map[metric]  # 指标决定颜色
                        ),
                        hoverinfo='text',
                        hovertext=hover_text
                    ))

        fig.update_layout(
            title="Metrics Trend",
            xaxis=dict(
                title="Time",
                tickformat="%H:%M:%S",
                tickangle=30,
                showgrid=False,
                gridcolor='#e0e0e0'
            ),
            yaxis=dict(
                title="Value",
                showgrid=False,
                gridcolor='#e0e0e0'
            ),
            legend_title="Legend",
            margin=dict(l=40, r=40, t=60, b=40),
            plot_bgcolor='white',
            paper_bgcolor='white'
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
    

def draw_csv(table_path: str):
    df = pd.read_csv(table_path, parse_dates=['timestamp'])

    df['index'] = pd.to_numeric(df['index'], errors='coerce')
    df = df.dropna(subset=['index'])
    df['index'] = df['index'].astype(int)

    unit_fields = [
        'clocks.current.memory [MHz]', 'temperature.memory',
        'clocks.current.sm [MHz]', 'temperature.gpu',
        'power.draw [W]', 'utilization.gpu [%]',
        'clocks.current.graphics [MHz]', 'utilization.memory [%]',
        'sm_active', 'sm_occupancy','tensor_active',
        'fp64_active', 'fp32_active', 'fp16_active',
        'usage.utilization [%]', 'dram_active', 'dram_usage',
        'pcie.link.gen.current', 'pcie.link.width.current',
        'pcie_tx_bytes', 'pcie_rx_bytes', 'nvlink_tx_bytes', 'nvlink_rx_bytes',
        'cpu_power', 'cpu_usage', 'dram_power'
    ]
    df = clean_units(df, unit_fields)
    app = create_dashboard(df)
    port = find_available_port()
    ip = get_server_ip()

    print(f"Dash 应用运行在 http://{ip}:{port}")
    app.run(debug=True, port=port, host='0.0.0.0', use_reloader=False)

