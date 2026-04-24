#!/usr/bin/env python3
"""
Simple test dashboard to verify Dash is working
"""
import dash
from dash import dcc, html
import os

app = dash.Dash(__name__)
server = app.server  # For Gunicorn

app.layout = html.Div([
    html.H1("MPC Dashboard Test"),
    html.P("✅ Dash is working!"),
    html.P("✅ Python imports working!"),
    html.P("✅ Basic server running!"),
    html.P("Next: Add back MPC features step by step...")
])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8089))
    app.run_server(host="0.0.0.0", port=port, debug=True)