#!/bin/bash

# Exit immediately if any command fails
set -e

echo "📦 Creating virtual environment..."
python3 -m venv venv

echo "📦 Activating virtual environment..."
source venv/bin/activate

echo "📦 Upgrading pip..."
pip install --upgrade pip

echo "📦 Installing required Python packages..."
pip install Flask playwright

echo "🎭 Installing Playwright browsers (Chromium, Firefox, WebKit)..."
playwright install

echo "✅ Setup complete! Run your app with:"
echo "source venv/bin/activate && python GPC_Automation.py"