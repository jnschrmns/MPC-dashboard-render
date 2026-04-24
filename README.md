# MPC Dashboard - Render Deployment

Sophisticated Model Predictive Control dashboard with external access via Render cloud platform.

## Features

- **Real-time MPC data visualization** from MAT files
- **Prediction verification** with 5-hour lead indicators (purple diamonds)
- **Weather emoji timeline** for intuitive forecasting
- **Power scaling correction** (factor 0.18) for heat pump data
- **Dynamic time axis** showing 15h past + 24h future
- **Override warning systems** for manual interventions

## Deployment

This repository is configured for automatic deployment on Render.com:

1. **Requirements**: All Python dependencies in `requirements.txt`
2. **Configuration**: Settings loaded from `config.yaml`
3. **Process**: Gunicorn WSGI server defined in `Procfile`
4. **Data**: 519+ MAT files included for live operation

## Live Data

The dashboard reads from MAT files in the `results/` directory. For live updates, ensure fresh MAT files are continuously uploaded to this location.

## External Access

Once deployed on Render, the dashboard will be accessible externally without VPN or local network requirements - perfect for monitoring your MPC system remotely.