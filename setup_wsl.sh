#!/bin/bash
set -e

echo "Setting up Voicebox backend in WSL..."

# Navigate to backend directory
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d ".venv_wsl" ]; then
    echo "Creating virtual environment (.venv_wsl)..."
    python3 -m venv .venv_wsl
fi

# Activate virtual environment
source .venv_wsl/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo "WSL Setup Complete!"
