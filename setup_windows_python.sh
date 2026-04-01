#!/bin/bash
echo "Downloading Windows Python 3.10..."
wget -nc -q --show-progress https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe

echo "Installing Windows Python into your Wine environment (this may take a minute, please wait)..."
# The /quiet flag installs it silently without popping up the Windows installer GUI
wine python-3.10-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

echo "Verifying Python Installation..."
wine python --version

echo "Installing your Robot Dependencies inside Wine..."
wine python -m pip install -r requirements.txt

echo "======================================"
echo "🎉 Setup Complete!"
echo "Check your .env file to make sure your credentials are set."
echo "You can now run your bot by typing:"
echo "wine python main.py"
echo "======================================"
