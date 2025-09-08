#!/bin/bash
# Script to run the Notion automation with environment variables from .env file

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Error: .env file not found!"
    echo "Please copy .env.template to .env and fill in your values."
    exit 1
fi

# Load environment variables from .env file
set -a
source .env
set +a

# Run the script
./venv/bin/python notion_script.py
