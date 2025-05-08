#!/bin/bash

# Exit on any error
set -e

echo "🚀 Setting up environment..."

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

echo "✅ Virtual environment created and activated."

# Upgrade pip
pip install --upgrade pip

# Install all required Python packages
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install

echo "✅ All setup complete! You can now run the app using: source venv/bin/activate && python app.py"
