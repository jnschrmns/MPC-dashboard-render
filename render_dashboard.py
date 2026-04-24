#!/usr/bin/env python3
"""
Pi Dashboard - MPC Dashboard for Raspberry Pi with external access
"""

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objs as go
import plotly.subplots as sp
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import scipy.io
import glob
from pathlib import Path
import sys
import os
import yaml
from github_mat_loader import GitHubMATLoader

def load_mpc_data_exact_match(results_dir="results", num_files=30):
    """Load data exactly like live_plot.py with weather information"""

    # Load config for scaling factor
    try:
        with open('config.yaml', 'r') as f:
            cfg = yaml.safe_load(f)
        hp_scale_factor = cfg.get('sensors', {}).get('hp_power_scale_factor', 1.0)
        sample_time_min_cfg = cfg.get('mpc', {}).get('sample_time_min', 30)
        print(f"DEBUG: Loaded HP scaling factor: {hp_scale_factor}")
    except Exception as e:
        print(f"Warning: Could not load config.yaml: {e}")
        hp_scale_factor = 1.0
        sample_time_min_cfg = 30

    # EMERGENCY FIX: Use local files only - GitHub loader causing issues
    print("DEBUG: Using local files only to fix loading issue")
    mat_files = sorted(glob.glob(str(Path(results_dir) / "*.mat")))[-num_files:]

    if not mat_files:
        return None, None, None

    # Load past data from multiple files
    past_data = []
    pred_lead_data = []  # Store prediction verification data
    recent_files = mat_files[-num_files:]
    prediction_lead_hours = 5  # Like live_plot.py default
    ts_min = 30  # 30 minute timesteps

    for mat_file in recent_files:
        try:
            d = scipy.io.loadmat(mat_file)
            filename = Path(mat_file).name
            if 'mpc_result_' in filename:
                date_str = filename.split('_')[2] + '_' + filename.split('_')[3].split('.')[0]
                timestamp = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            else:
                continue

            # Extract measured data exactly like live_plot.py
            pel_net_raw = float(d.get('Pel_net_measured', [[0]])[0,0])
            pv_meas_raw = float(d.get('Pv_measured', [[0]])[0,0])

            # Apply scaling factor to retrospectively correct the power measurements
            # Original: Pel_net = HP - PV, so HP = Pel_net + PV
            hp_energy_original = pel_net_raw + pv_meas_raw
            hp_energy_scaled = hp_energy_original * hp_scale_factor
            pel_net_scaled = hp_energy_scaled - pv_meas_raw  # Scaled HP - original PV

            # Get override warning if present
            override_warning = d.get('override_warning', [''])
            warning_text = ''
            if isinstance(override_warning, (list, np.ndarray)) and len(override_warning) > 0:
                warning_text = str(override_warning[0]) if override_warning[0] else ''
            elif isinstance(override_warning, str):
                warning_text = override_warning

            row = {
                'time': timestamp,
                'Tt_meas': float(d.get('Tt_meas', [[0]])[0,0]),
                'Twk_meas': float(d.get('Twk_meas', [[0]])[0,0]),
                'Ta_meas': float(d.get('Ta_current', [[0]])[0,0]),
                'Ttsp_applied': float(d.get('Ttsp_applied', [[0]])[0,0]),
                'Twksp_applied': float(d.get('Twksp_applied', [[0]])[0,0]),
                'Power_meas': pel_net_scaled,  # Use scaled power instead of raw
                'PV_meas': pv_meas_raw,  # Keep original PV measurements
                'DHW': bool(d.get('is_dhw', [[False]])[0,0]),
                'override_warning': warning_text,  # Add override warning
            }

            # Price
            pricev = d.get('pricev', [[0]])
            row['Price'] = float(pricev.flat[0] if hasattr(pricev, 'flat') and len(pricev.flat) > 0 else 0)

            # Tmin
            tmin_mat = d.get('Tmin_par', d.get('Tmin', [[0], [0]]))
            if np.atleast_2d(tmin_mat).shape[0] >= 2:
                tm = np.atleast_2d(tmin_mat)
                row['Tmin_t'] = float(tm[0, 0])
                row['Tmin_w'] = float(tm[1, 0])
            else:
                row['Tmin_t'] = 0.0
                row['Tmin_w'] = 0.0

            past_data.append(row)

            # Extract prediction verification data (like live_plot.py lines 204-235)
            youtv = d.get('Youtv', None)
            if youtv is not None and youtv.ndim == 2:
                step_x = min(int(round(prediction_lead_hours * 60 / ts_min)) - 1, youtv.shape[0] - 1)
                if step_x >= 0:
                    t_target = timestamp + timedelta(hours=prediction_lead_hours)

                    pred_row = {
                        't_target': t_target,
                        'Tt_pred': float(youtv[step_x, 2]),
                        'Twk_pred': float(youtv[step_x, 3]),
                        'Ttsp_pred': float(youtv[step_x, 0]),
                        'Twksp_pred': float(youtv[step_x, 1]),
                        'Pel_pred': float(youtv[step_x, 4]),
                        'PV_pred': float(youtv[step_x, 7]) if youtv.shape[1] > 7 else 0.0,
                    }

                    # Add price and Ta predictions
                    pricev_mat = d.get('pricev', None)
                    if pricev_mat is not None and len(pricev_mat.flat) > step_x:
                        pred_row['Price_pred'] = float(pricev_mat.flat[step_x])
                    else:
                        pred_row['Price_pred'] = 0.0

                    tav_mat = d.get('Tav_par', d.get('Tav', None))
                    if tav_mat is not None and len(tav_mat.flat) > step_x:
                        pred_row['Ta_pred'] = float(tav_mat.flat[step_x])
                    else:
                        pred_row['Ta_pred'] = 0.0

                    pred_lead_data.append(pred_row)

        except Exception as e:
            print(f"Error loading {mat_file}: {e}")
            continue

    past_df = pd.DataFrame(past_data)

    # Filter to show reasonable amount of past data (36 hours before latest data)
    if not past_df.empty:
        latest_time = past_df['time'].max()
        cutoff = latest_time - timedelta(hours=36)
        past_df = past_df[past_df['time'] > cutoff].copy()

    # Load predictions from latest file
    latest_file = mat_files[-1]
    pred_data = None
    try:
        d = scipy.io.loadmat(latest_file)
        filename = Path(latest_file).name
        if 'mpc_result_' in filename:
            date_str = filename.split('_')[2] + '_' + filename.split('_')[3].split('.')[0]
            pred_start = datetime.strptime(date_str, '%Y%m%d_%H%M%S')

        # Extract predictions exactly like live_plot.py
        tav_pred = d.get('Tav', None)
        youtv = d.get('Youtv', None)

        if tav_pred is not None and youtv is not None:
            tav_pred = np.atleast_2d(tav_pred)
            youtv = np.atleast_2d(youtv)

            n_pred_steps = min(48, youtv.shape[0], tav_pred.shape[1])

            # Build prediction times starting from pred_start
            pred_times = [pred_start + timedelta(minutes=k * 30) for k in range(1, n_pred_steps+1)]

            # Extract future Tmin predictions
            tmin_pred = d.get('Tmin_par', d.get('Tmin', None))
            if tmin_pred is not None:
                tmin_pred = np.atleast_2d(tmin_pred)

            price_pred = d.get('pricev', None)

            pred_data = {
                'time': pred_times,
                'Ta_pred': tav_pred[0, 1:n_pred_steps+1],
                'Tt_pred': youtv[1:n_pred_steps+1, 2],
                'Twk_pred': youtv[1:n_pred_steps+1, 3],
                'Ttsp_pred': youtv[1:n_pred_steps+1, 0],
                'Twksp_pred': youtv[1:n_pred_steps+1, 1],
                'Tmin_t_pred': tmin_pred[0, 1:n_pred_steps+1] if tmin_pred is not None else [0] * n_pred_steps,
                'Tmin_w_pred': tmin_pred[1, 1:n_pred_steps+1] if tmin_pred is not None else [0] * n_pred_steps,
                'Pel_net_pred': youtv[1:n_pred_steps+1, 4] if youtv.shape[1] > 4 else [0] * n_pred_steps,
                'PV_pred': youtv[1:n_pred_steps+1, 7] if youtv.shape[1] > 7 else [0] * n_pred_steps,
                'Price_pred': price_pred[0, 1:n_pred_steps+1] if price_pred is not None and np.array(price_pred).shape[1] > n_pred_steps else [0] * n_pred_steps,
            }
            pred_data = pd.DataFrame(pred_data)

    except Exception as e:
        print(f"Error loading predictions: {e}")

    # Process prediction verification data
    pred_lead_df = None
    if pred_lead_data:
        pred_lead_df = pd.DataFrame(pred_lead_data)
        print(f"DEBUG: Created pred_lead_df with {len(pred_lead_df)} verification points")

    # Create weather emoji timeline
    def get_weather_emoji(hour):
        """Simple weather emoji mapping based on time of day"""
        if 6 <= hour <= 18:  # Daytime
            if hour <= 8 or hour >= 17:
                return '🌤️'  # Partly cloudy
            elif hour <= 12:
                return '☀️'   # Sunny
            else:
                return '⛅'   # Partly cloudy
        else:  # Nighttime
            return '🌙'       # Moon

    # Generate weather timeline
    time_range = pd.date_range(start=past_df['time'].min(),
                              end=past_df['time'].max() + timedelta(hours=24),
                              freq='3H')

    weather_info = {
        'time': time_range,
        'emoji': [get_weather_emoji(t.hour) for t in time_range],
        'temp': 20.0,
        'solar': 500,
        'clouds': 25
    }

    return past_df, pred_data, pred_lead_df, weather_info, sample_time_min_cfg

def create_exact_match_figure(past_df, pred_df, pred_lead_df=None, weather_info=None, sample_time_min=30, cfg=None):
    """Create figure exactly matching live_plot.py colors and layout"""

    # Load config for axis settings
    if cfg is None:
        try:
            with open('config.yaml', 'r') as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Could not load config.yaml: {e}")
            cfg = {}

    # Get axis configuration from config (correct path)
    past_display_hours = cfg.get('mpc', {}).get('past_display_hours', 15)
    future_display_hours = cfg.get('mpc', {}).get('future_display_hours', 24)
    if past_df is None or past_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data available", x=0.5, y=0.5, showarrow=False)
        return fig

    # Create subplots
    fig = sp.make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        subplot_titles=["Tinyhouse (+ ambient)", "Woonkamer", "Electrical power, price"],
        vertical_spacing=0.15,
        row_heights=[0.32, 0.32, 0.36]
    )

    # SUBPLOT 1: TINYHOUSE
    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Tt_meas'],
        name='Tt meas', line=dict(color='blue', width=2),
        mode='lines', showlegend=False
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Ttsp_applied'],
        name='Ttsp applied', line=dict(color='black', width=1.5),
        mode='lines', showlegend=False
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Tmin_t'],
        name='Tmin', line=dict(color='red', width=1.5),
        mode='lines', showlegend=False
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Ta_meas'],
        name='Ta', line=dict(color='gray', width=1.5),
        mode='lines', showlegend=False
    ), row=1, col=1)

    # PREDICTIONS for Tinyhouse
    if pred_df is not None and not pred_df.empty:
        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Tt_pred'],
            name='', line=dict(color='blue', width=2.5, dash='dash'),
            showlegend=False
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Ttsp_pred'],
            name='', line=dict(color='black', width=2, dash='dash'),
            showlegend=False
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Ta_pred'],
            name='', line=dict(color='gray', width=2.5, dash='dash'),
            showlegend=False
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Tmin_t_pred'],
            name='', line=dict(color='red', width=2.5, dash='dash'),
            showlegend=False
        ), row=1, col=1)

    # SUBPLOT 2: WOONKAMER
    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Twk_meas'],
        name='Twk meas', line=dict(color='blue', width=2),
        mode='lines', showlegend=False
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Twksp_applied'],
        name='Twksp applied', line=dict(color='black', width=1.5),
        mode='lines', showlegend=False
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['Tmin_w'],
        name='Tmin wk', line=dict(color='red', width=1.5),
        mode='lines', showlegend=False
    ), row=2, col=1)

    # PREDICTIONS for Woonkamer
    if pred_df is not None and not pred_df.empty:
        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Twk_pred'],
            name='', line=dict(color='blue', width=2.5, dash='dash'),
            showlegend=False
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Twksp_pred'],
            name='', line=dict(color='black', width=2, dash='dash'),
            showlegend=False
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Tmin_w_pred'],
            name='', line=dict(color='red', width=2.5, dash='dash'),
            showlegend=False
        ), row=2, col=1)

    # PREDICTION VERIFICATION LINES (pred 5h)
    if pred_lead_df is not None and not pred_lead_df.empty:
        print(f"DEBUG: Adding {len(pred_lead_df)} prediction verification points")

        # Add vertical lines and dots for each prediction target
        for _, row in pred_lead_df.iterrows():
            t_target = row['t_target']

            # Add vertical lines across both temperature subplots
            fig.add_shape(
                type="line",
                x0=t_target, x1=t_target,
                y0=0, y1=1,
                yref="y domain",
                line=dict(color="purple", width=1, dash="dot"),
                row=1, col=1
            )

            fig.add_shape(
                type="line",
                x0=t_target, x1=t_target,
                y0=0, y1=1,
                yref="y domain",
                line=dict(color="purple", width=1, dash="dot"),
                row=2, col=1
            )

            # Add prediction verification dots only
            fig.add_trace(go.Scatter(
                x=[t_target], y=[row['Tt_pred']],
                mode='markers',
                marker=dict(color='purple', size=3, symbol='circle'),
                name='pred 5h', showlegend=False
            ), row=1, col=1)

            fig.add_trace(go.Scatter(
                x=[t_target], y=[row['Twk_pred']],
                mode='markers',
                marker=dict(color='purple', size=3, symbol='circle'),
                name='pred 5h', showlegend=False
            ), row=2, col=1)

            # Add "pred 5h" text label (only once for clarity)
            if idx == 0:  # Only add label for first point
                fig.add_annotation(
                    x=t_target, y=row['Tt_pred'] + 0.5,
                    text="pred 5h", showarrow=False,
                    font=dict(size=10, color='purple'),
                    row=1, col=1
                )

    # SUBPLOT 3: POWER
    if not past_df.empty:
        power_averaged = past_df.copy()
        power_averaged['time_group'] = power_averaged['time'].dt.floor(f'{sample_time_min}min')
        power_grouped = power_averaged.groupby('time_group')['Power_meas'].mean().reset_index()

    fig.add_trace(go.Bar(
        x=power_grouped['time_group'], y=power_grouped['Power_meas'],
        name='Pel_net meas', marker=dict(color='blue', opacity=0.7),
        showlegend=False
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=past_df['PV_meas'],
        name='PV', line=dict(color='orange', width=2),
        mode='lines', showlegend=False
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=past_df['time'], y=[10 * p for p in past_df['Price']],
        name='10×price', line=dict(color='green', width=1.5),
        mode='lines', showlegend=False
    ), row=3, col=1)

    # PREDICTIONS for Power
    if pred_df is not None and not pred_df.empty:
        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['Pel_net_pred'],
            name='', line=dict(color='blue', width=3, dash='dash'),
            showlegend=False
        ), row=3, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=pred_df['PV_pred'],
            name='', line=dict(color='orange', width=2.5, dash='dash'),
            showlegend=False
        ), row=3, col=1)

        fig.add_trace(go.Scatter(
            x=pred_df['time'], y=[10 * p for p in pred_df['Price_pred']],
            name='', line=dict(color='green', width=2.5, dash='dash'),
            showlegend=False
        ), row=3, col=1)

    # DHW periods - using timedelta directly from imports
    dhw_periods = past_df[past_df['DHW'] == True]
    for _, period in dhw_periods.iterrows():
        fig.add_vrect(
            x0=period['time'] - timedelta(minutes=15),
            x1=period['time'] + timedelta(minutes=15),
            fillcolor='cyan', opacity=0.25, row=3, col=1
        )

    # Add weather emojis to timeline
    if weather_info and 'time' in weather_info and 'emoji' in weather_info:
        for time_point, emoji in zip(weather_info['time'], weather_info['emoji']):
            # Add emoji annotations at top of each subplot
            for row_num in [1, 2, 3]:
                fig.add_annotation(
                    x=time_point, y=1.02,
                    xref='x', yref=f'y{row_num} domain',
                    text=emoji, showarrow=False,
                    font=dict(size=14),
                    row=row_num, col=1
                )

    # Check for override warnings and add warning display like live_plot.py
    override_warnings = []
    if past_df is not None and not past_df.empty:
        # Check for any recent override warnings (last few data points)
        recent_warnings = past_df[past_df['override_warning'].str.len() > 0]['override_warning'].tolist()
        if recent_warnings:
            # Get the most recent warning
            override_warnings = [recent_warnings[-1]]

    # Layout
    fig.update_layout(
        height=900,
        showlegend=False,
        template="plotly_white",
        autosize=True,
        margin=dict(l=80, r=50, t=80, b=80),
    )

    # Remove excessive grid lines for clean appearance
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='lightgray', griddash='solid')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray', griddash='solid')

    # Add override warning display if present - like live_plot.py
    if override_warnings:
        warning_text = override_warnings[0]
        fig.add_annotation(
            x=0.5, y=0.99,  # Top center of entire figure
            xref="paper", yref="paper",
            text=f"⚠ {warning_text}",
            showarrow=False,
            bgcolor="lightyellow",
            bordercolor="red",
            borderwidth=2,
            font=dict(size=12, color='red', family="Arial, sans-serif"),
            xanchor="center",
            yanchor="top",
            borderpad=8
        )

    # Add legend boxes
    fig.add_annotation(
        x=0.98, y=0.05,
        xref="x domain", yref="y domain",
        text="<span style='color:blue'>■</span> Tt<br>" +
             "<span style='color:black'>■</span> Ttsp<br>" +
             "<span style='color:red'>■</span> Tmin<br>" +
             "<span style='color:gray'>■</span> Ta",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="lightgrey",
        borderwidth=1,
        font=dict(size=16, family="Arial, sans-serif"),
        xanchor="right",
        yanchor="bottom",
        align="left"
    )

    fig.add_annotation(
        x=0.98, y=0.95,
        xref="x2 domain", yref="y2 domain",
        text="<span style='color:blue'>■</span> Twk<br>" +
             "<span style='color:black'>■</span> Twksp<br>" +
             "<span style='color:red'>■</span> Tmin wk",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="lightgrey",
        borderwidth=1,
        font=dict(size=16, family="Arial, sans-serif"),
        xanchor="right",
        yanchor="top",
        align="left"
    )

    fig.add_annotation(
        x=0.98, y=0.95,
        xref="x3 domain", yref="y3 domain",
        text="<span style='color:blue'>■</span> Pel_net<br>" +
             "<span style='color:orange'>■</span> PV<br>" +
             "<span style='color:green'>■</span> 10×price",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="lightgrey",
        borderwidth=1,
        font=dict(size=16, family="Arial, sans-serif"),
        xanchor="right",
        yanchor="top",
        align="left"
    )

    # Y-axes
    fig.update_yaxes(title_text="°C", row=1, col=1)
    fig.update_yaxes(title_text="°C", range=[10, 25], row=2, col=1)
    fig.update_yaxes(title_text="kW", row=3, col=1)
    fig.update_xaxes(title_text="Time", showticklabels=True, row=1, col=1)
    fig.update_xaxes(title_text="Time", row=3, col=1)

    # Set axis limits using config values
    if past_df is not None and not past_df.empty:
        # Use actual current time, not data time
        now = datetime.now()
        data_latest = past_df['time'].max()
        x_left = now - timedelta(hours=past_display_hours)
        x_right = now + timedelta(hours=future_display_hours)
        print(f"DEBUG: Current time: {now.strftime('%H:%M')}, Latest data: {data_latest.strftime('%H:%M')}")
        print(f"DEBUG: Setting axis range: {past_display_hours}h past + {future_display_hours}h future")

        if pred_df is not None and not pred_df.empty:
            pred_end = pred_df['time'].max()
            if pred_end > x_right:
                x_right = pred_end

        for row in [1, 2, 3]:
            fig.update_xaxes(range=[x_left, x_right], row=row, col=1)

    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True, autorange=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True, autorange=True)

    return fig

# Create Dash app
app = dash.Dash(__name__)

print("Loading data...")
past_df, pred_df, pred_lead_df, weather_info, sample_time_min = load_mpc_data_exact_match("results", 50)

# Create initial figure
if past_df is not None and not past_df.empty:
    print(f"SUCCESS: Loaded {len(past_df)} past data points")
    if pred_df is not None:
        print(f"SUCCESS: Loaded {len(pred_df)} prediction points")
    test_fig = create_exact_match_figure(past_df, pred_df, pred_lead_df, weather_info, sample_time_min)
    print(f"SUCCESS: Created figure")
else:
    print("WARNING: No data loaded - creating empty dashboard")
    test_fig = go.Figure()
    test_fig.add_annotation(
        text="MPC Dashboard - Waiting for data...<br>Please sync MAT files from Pi",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=20)
    )

app.layout = html.Div([
    html.Div(id="data-info", style={'textAlign': 'center', 'margin': '20px'}),
    dcc.Graph(id="mpc-plot", figure=test_fig, style={'height': '900px'}),
    dcc.Interval(id='interval', interval=5*60*1000, n_intervals=0)  # 5 minutes
])

@app.callback(
    [Output('mpc-plot', 'figure'), Output('data-info', 'children')],
    [Input('interval', 'n_intervals')]
)
def update_dashboard(n):
    try:
        past_df, pred_df, pred_lead_df, weather_info, sample_time_min = load_mpc_data_exact_match("results", 50)
        if past_df is None or past_df.empty:
            empty_fig = go.Figure()
            empty_fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
            return empty_fig, "No data available"

        fig = create_exact_match_figure(past_df, pred_df, pred_lead_df, weather_info, sample_time_min)
        return fig, ""

    except Exception as e:
        error_fig = go.Figure()
        error_fig.add_annotation(text=f"Error: {str(e)}", x=0.5, y=0.5, showarrow=False)
        return error_fig, f"Error: {str(e)}"

# For Render deployment
server = app.server

if __name__ == "__main__":
    print("=== MPC Dashboard ===")
    port = int(os.environ.get("PORT", 8089))
    print(f"Starting dashboard on port {port}")
    app.run(debug=False, port=port, host="0.0.0.0")