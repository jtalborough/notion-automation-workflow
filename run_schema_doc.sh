#!/bin/bash
# Script to run the Notion schema documenter with environment variables from .env file

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

# Run the schema documenter script
echo "Running Notion schema documenter..."
python document_schema.py

# Check if the schema files were created
if [ -f "schema/task_schema.json" ] && [ -f "schema/notebook_schema.json" ] && [ -f "schema/property_mapping.json" ]; then
    echo "Schema documentation completed successfully!"
    echo "Created files in schema/ directory:"
    echo "  - task_schema.json"
    echo "  - notebook_schema.json"
    echo "  - property_mapping.json"
else
    echo "Warning: Some schema files were not created."
    echo "Check the logs above for errors."
fi
