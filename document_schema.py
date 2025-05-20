#!/usr/bin/env python3
"""
A utility script to document Notion database schemas for proper property mapping.
This helps reveal the property names, IDs, and types in both databases for accurate mapping.
"""

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class NotionSchemaDocumenter:
    def __init__(self):
        """Initialize the Notion Schema Documenter."""
        self.api_token = os.environ.get("NOTION_API_TOKEN")
        self.task_database_id = os.environ.get("TASK_DATABASE_ID", "a3b073d5b30d48089bd9eb62ed180e15")
        self.notebook_database_id = os.environ.get("NOTEBOOK_DATABASE_ID", "1f5d6c20dc718089ae02eea25fb480f5")
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

    def document_database_schema(self, database_id: str) -> Dict[str, Any]:
        """
        Retrieve and document the schema of a Notion database.
        
        Args:
            database_id: The ID of the Notion database
            
        Returns:
            Dictionary containing the database properties and their details
        """
        url = f"https://api.notion.com/v1/databases/{database_id}"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            database_name = data.get("title", [{}])[0].get("plain_text", "Unknown Database")
            
            # Extract properties
            properties = {}
            for prop_id, prop_details in data.get("properties", {}).items():
                prop_name = prop_details.get("name", "")
                prop_type = prop_details.get("type", "unknown")
                
                property_info = {
                    "name": prop_name,
                    "type": prop_type,
                    "id": prop_id
                }
                
                # Extract options for select and multi_select properties
                if prop_type in ["select", "multi_select"] and "options" in prop_details.get(prop_type, {}):
                    options = [option.get("name", "") for option in prop_details.get(prop_type, {}).get("options", [])]
                    property_info["options"] = options
                elif prop_type == "status":
                    options = [option.get("name", "") for option in prop_details.get("status", {}).get("options", [])]
                    property_info["options"] = options
                
                properties[prop_id] = property_info
            
            return {
                "database_name": database_name,
                "properties": properties,
                "raw_response": data  # Include the complete Notion API response
            }
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error retrieving database schema: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error retrieving database schema: {e}")
            return {"error": str(e)}
    
    def create_property_mapping(self, task_schema: Dict[str, Any], notebook_schema: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate a mapping between task and notebook properties based on property names.
        
        Args:
            task_schema: The schema of the task database
            notebook_schema: The schema of the notebook database
            
        Returns:
            Dictionary mapping task property IDs to notebook property IDs
        """
        mapping = {}
        
        # Create name-to-id mappings for each database
        task_name_to_id = {prop["name"]: prop_id for prop_id, prop in task_schema["properties"].items()}
        notebook_name_to_id = {prop["name"]: prop_id for prop_id, prop in notebook_schema["properties"].items()}
        
        # Create mapping based on matching names
        for prop_name, task_prop_id in task_name_to_id.items():
            if prop_name in notebook_name_to_id:
                notebook_prop_id = notebook_name_to_id[prop_name]
                mapping[task_prop_id] = notebook_prop_id
                
        return mapping
    
    def document_schemas(self):
        """Document and display the schemas of both databases."""
        logger.info("Retrieving Task database schema...")
        task_schema = self.document_database_schema(self.task_database_id)
        
        logger.info("Retrieving Notebook database schema...")
        notebook_schema = self.document_database_schema(self.notebook_database_id)
        
        if "error" in task_schema or "error" in notebook_schema:
            logger.error("Could not document schemas due to errors.")
            return
        
        # Create mapping between properties
        property_mapping = self.create_property_mapping(task_schema, notebook_schema)
        
        # Save schemas to files
        self.save_schema_to_file(task_schema, "task_schema.json")
        self.save_schema_to_file(notebook_schema, "notebook_schema.json")
        
        with open("schema/property_mapping.json", "w") as f:
            json.dump(property_mapping, f, indent=2)
        
        # Print summary
        logger.info(f"Task Database: {task_schema.get('database_name')} - {len(task_schema.get('properties', {}))} properties")
        logger.info(f"Notebook Database: {notebook_schema.get('database_name')} - {len(notebook_schema.get('properties', {}))} properties")
        logger.info(f"Property Mapping: {len(property_mapping)} properties mapped")
        
        # Print property details for both databases
        self._print_property_details("Task Database Properties:", task_schema)
        self._print_property_details("Notebook Database Properties:", notebook_schema)
        
        # Print the mapping
        logger.info("Property Mapping (Task -> Notebook):")
        for task_prop_id, notebook_prop_id in property_mapping.items():
            task_name = task_schema["properties"][task_prop_id]["name"]
            notebook_name = notebook_schema["properties"][notebook_prop_id]["name"]
            logger.info(f"  {task_name} ({task_prop_id}) -> {notebook_name} ({notebook_prop_id})")
    
    def save_schema_to_file(self, schema: dict, filename: str) -> None:
        """Save the schema to a JSON file with the complete API response."""
        # Ensure the schema directory exists
        schema_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")
        os.makedirs(schema_dir, exist_ok=True)
        
        file_path = os.path.join(schema_dir, filename)
        
        # Create a structured version including both the extracted schema and raw API response
        output_data = {
            "database_name": schema.get("database_name"),
            "properties": schema.get("properties", {}),
            "raw_api_response": schema.get("raw_response", {})  # Include the full API response
        }
        
        try:
            with open(file_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            logger.info(f"Schema with raw API response saved to {file_path}")
        except Exception as e:
            logger.error(f"Error saving schema to {file_path}: {e}")

    def _print_property_details(self, title: str, schema: Dict[str, Any]):
        """Print detailed information about database properties."""
        logger.info(title)
        logger.info("" + "=" * 80)
        logger.info(f"{'Property Name':<30} | {'Property ID':<40} | {'Type':<15} | Options")
        logger.info("-" * 100)
        
        # Sort properties by name for easier reading
        sorted_props = sorted(schema.get("properties", {}).items(), key=lambda item: item[1].get("name", ""))
        
        for prop_id, prop_info in sorted_props:
            prop_name = prop_info["name"]
            prop_type = prop_info["type"]
            options_str = ""
            
            if "options" in prop_info:
                options_str = f"{', '.join(prop_info['options'])}"
                
            logger.info(f"{prop_name:<30} | {prop_id:<40} | {prop_type:<15} | {options_str}")
        
        logger.info("" + "=" * 80)

if __name__ == "__main__":
    documenter = NotionSchemaDocumenter()
    documenter.document_schemas()
