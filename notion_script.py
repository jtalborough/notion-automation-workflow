import requests
import os
import re
import json
import logging
import urllib.parse
from dotenv import load_dotenv
from typing import Dict, List, Any, Optional, Tuple
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN")
TASK_DATABASE_ID = os.getenv("TASK_DATABASE_ID")
NOTEBOOK_DATABASE_ID = os.getenv("NOTEBOOK_DATABASE_ID")

# Define patterns for recurring tasks
RECURRING_RELATIVE_PATTERN = re.compile(r"rec[-_](\d+)([dwm])")
RECURRING_WEEKLY_PATTERN = re.compile(r"rec[-_]weekly[-_](\w{3})")
RECURRING_MONTHLY_PATTERN = re.compile(r"rec[-_]monthly[-_](\d{1,2})")

# Map weekday abbreviations to integers (Monday=0, Sunday=6)
WEEKDAY_MAP = {
    'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6,
    'm': 0, 't': 1, 'w': 2, 'th': 3, 'f': 4, 'sa': 5, 'su': 6,
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
}

class NotionClientWrapper:
    """Wrapper for the Notion API client to handle common operations."""
    
    def __init__(self, api_token: Optional[str] = None):
        """Initialize the Notion client with an API token."""
        self.api_token = api_token or NOTION_API_TOKEN
        if not self.api_token:
            raise ValueError("NOTION_API_TOKEN must be set in environment variables")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        self.base_url = "https://api.notion.com/v1"
        
    def query_database(self, database_id: str, filter_dict: Optional[Dict] = None, 
                       sorts: Optional[List] = None) -> List[Dict[str, Any]]:
        """Query a Notion database with optional filters and sorts."""
        url = f"{self.base_url}/databases/{database_id}/query"
        
        payload = {}
        if filter_dict:
            payload["filter"] = filter_dict
        if sorts:
            payload["sorts"] = sorts
            
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code != 200:
            logger.error(f"Error querying database: {response.text}")
            response.raise_for_status()
            
        return response.json().get("results", [])
        
    def get_page(self, page_id: str) -> Dict[str, Any]:
        """Get a Notion page by its ID."""
        url = f"{self.base_url}/pages/{page_id}"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            logger.error(f"Error getting page: {response.text}")
            response.raise_for_status()
            
        return response.json()
        
    def update_page(self, page_id: str, properties: Optional[Dict] = None, 
                    archived: Optional[bool] = None, children: Optional[List] = None) -> Dict[str, Any]:
        """Update a Notion page with new properties or archive status."""
        url = f"{self.base_url}/pages/{page_id}"
        
        payload = {}
        if properties is not None:
            payload["properties"] = properties
        if archived is not None:
            payload["archived"] = archived
            
        response = requests.patch(url, headers=self.headers, json=payload)
        
        if response.status_code != 200:
            logger.error(f"Error updating page: {response.text}")
            response.raise_for_status()
            
        return response.json()
        
    def create_page(self, parent_id: str, properties: Dict, is_database: bool = False, 
                    children: Optional[List] = None, title_for_api: Optional[str] = None) -> Dict[str, Any]:
        """Create a new page in a Notion database or as a child of another page."""
        url = f"{self.base_url}/pages"
        
        parent = {}
        if is_database:
            parent = {"database_id": parent_id}
        else:
            parent = {"page_id": parent_id}
            
        # Make a clean copy of properties
        clean_properties = properties.copy()
        
        # If title_for_api is provided, ensure it's set correctly in the properties
        if title_for_api:
            logger.info(f"Setting title directly from API parameter: '{title_for_api}'")
            
            # For database entries, title must be in the properties
            if is_database:
                # Set the title field - this field must be named exactly as it appears in the database schema
                clean_properties["Name"] = {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": title_for_api}
                        }
                    ]
                }
            
        payload = {
            "parent": parent,
            "properties": clean_properties
        }
        
        if children:
            payload["children"] = children
            
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code != 200:
            logger.error(f"Error creating page: {response.text}")
            response.raise_for_status()
            
        return response.json()
        
    def get_all_block_children(self, block_id: str) -> List[Dict[str, Any]]:
        """Get all child blocks of a block, handling pagination."""
        url = f"{self.base_url}/blocks/{block_id}/children"
        
        all_blocks = []
        has_more = True
        start_cursor = None
        
        logger.info(f"Fetching blocks for block ID: {block_id}")
        
        while has_more:
            params = {}
            if start_cursor:
                params["start_cursor"] = start_cursor
                
            logger.info(f"Making API request to {url} for blocks")
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code != 200:
                logger.error(f"Error getting block children: {response.text}")
                response.raise_for_status()
                
            result = response.json()
            page_blocks = result.get("results", [])
            logger.info(f"Received {len(page_blocks)} blocks from API in this page")
            all_blocks.extend(page_blocks)
            
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")
            
            if has_more:
                logger.info(f"More blocks available, continuing with cursor: {start_cursor}")
        
        logger.info(f"Total blocks fetched: {len(all_blocks)}")
        
        # Log block types if any blocks were found
        if all_blocks:
            block_types = {}
            for block in all_blocks:
                block_type = block.get("type", "unknown")
                block_types[block_type] = block_types.get(block_type, 0) + 1
            logger.info(f"Block types summary: {block_types}")
            
            # Log first block as an example if there are any
            if len(all_blocks) > 0:
                first_block = all_blocks[0]
                logger.info(f"First block type: {first_block.get('type', 'unknown')}, ID: {first_block.get('id', 'unknown')}")
        else:
            logger.warning(f"No blocks found for block ID: {block_id}")
            
        return all_blocks

class TaskService:
    """Service for handling task operations in Notion."""

    def __init__(self, notion_client: Optional[NotionClientWrapper] = None):
        """Initialize the task service with a Notion client."""
        self.notion = notion_client or NotionClientWrapper()
        self.task_database_id = TASK_DATABASE_ID
        self.notebook_database_id = NOTEBOOK_DATABASE_ID
        if not self.task_database_id or not self.notebook_database_id:
            raise ValueError("TASK_DATABASE_ID and NOTEBOOK_DATABASE_ID must be set.")
        self._validate_database_access()

    def _validate_database_access(self):
        """Validate that the databases exist and are accessible."""
        try:
            self.notion.query_database(self.task_database_id, sorts=[{"property": "Created", "direction": "descending"}])
            logger.info("Successfully connected to the Task database.")
        except Exception as e:
            logger.error(f"Failed to connect to the Task database: {e}")
            raise
        try:
            self.notion.query_database(self.notebook_database_id, sorts=[{"property": "Created", "direction": "descending"}])
            logger.info("Successfully connected to the Notebook database.")
        except Exception as e:
            logger.error(f"Failed to connect to the Notebook database: {e}")
            raise

    def move_task_to_notebook(self, task_id: str) -> Dict[str, Any]:
        """Move a completed task to the Notebook DB and handle sub-tasks/archiving."""
        task = self.notion.get_page(task_id)
        parent_db_id = task.get("parent", {}).get("database_id", "")
        if parent_db_id.replace("-", "") != self.task_database_id.replace("-", ""):
            raise ValueError(f"Task {task_id} is not from the task database")

        is_recurring = self._is_recurring_task(task)
        blocks = self.notion.get_all_block_children(task_id)
        created_todo_tasks = self._create_tasks_from_open_todos(task, blocks)

        notebook_properties = self._map_task_to_notebook_properties(task)
        filtered_blocks = self._filter_safe_blocks(blocks)

        new_page = self.notion.create_page(
            parent_id=self.notebook_database_id,
            properties=notebook_properties,
            is_database=True,
            children=filtered_blocks
        )
        logger.info(f"Successfully moved task {task_id} to notebook page {new_page['id']}")

        if is_recurring:
            self._handle_recurring_task(task)
        else:
            self.notion.update_page(page_id=task_id, archived=True)
            logger.info(f"Archived non-recurring task {task_id}")

        return {
            "original_task_id": task_id,
            "new_notebook_page_id": new_page["id"],
            "created_todo_tasks": created_todo_tasks
        }

    def process_all_completed_tasks(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Finds and processes all 'Done' tasks."""
        filter_dict = {"property": "Status", "status": {"equals": "Done"}}
        logger.info("Querying for tasks with status 'Done'")
        done_tasks = self.notion.query_database(self.task_database_id, filter_dict)
        logger.info(f"Found {len(done_tasks)} tasks to process.")

        recurring_results, non_recurring_results = [], []
        for task in done_tasks:
            task_id = task["id"]
            try:
                logger.info(f"Processing task: {task_id}")
                result = self.move_task_to_notebook(task_id)
                if self._is_recurring_task(task):
                    recurring_results.append(result)
                else:
                    non_recurring_results.append(result)
            except Exception as e:
                logger.error(f"Failed to process task {task_id}: {e}", exc_info=True)

        return recurring_results, non_recurring_results

    def _map_task_to_notebook_properties(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Maps properties from a task to the format for a new notebook page."""
        task_properties = task.get("properties", {})
        notebook_properties = {}

        # Define the properties to copy from Task to Notebook
        # This ensures we only copy properties that exist and are expected
        property_map = [
            "Status", "Tag", "Priority", "Type", "Location", "DoneDate", "DoDate",
            "Project", "People", "URL", "Time", "Cost", "Done"
        ]

        # 1. Handle the Title property. The destination property is 'Title'.
        title_key = next((k for k, v in task_properties.items() if v.get('type') == 'title'), None)
        if title_key:
            plain_text_title = "".join(t.get("plain_text", "") for t in task_properties[title_key].get("title", []))
            notebook_properties["Title"] = {"title": [{"text": {"content": plain_text_title}}]}

        # 2. Handle all other properties based on the explicit map
        for prop_name in property_map:
            if prop_name in task_properties:
                prop_data = task_properties[prop_name]
                prop_type = prop_data.get("type")
                value = prop_data.get(prop_type)

                # Ensure we don't copy empty values, which can cause validation errors
                if value is not None:
                    notebook_properties[prop_name] = {prop_type: value}
        
        logger.info(f"Mapped properties for notebook page: {list(notebook_properties.keys())}")
        return notebook_properties

    def _is_recurring_task(self, task: Dict[str, Any]) -> bool:
        """Checks if a task is recurring."""
        properties = task.get("properties", {})
        if properties.get("Recurring", {}).get("formula", {}).get("boolean"): 
            return True
        tags = properties.get("Tag", {}).get("multi_select", [])
        return any(RECURRING_RELATIVE_PATTERN.match(t["name"]) or RECURRING_WEEKLY_PATTERN.match(t["name"]) or RECURRING_MONTHLY_PATTERN.match(t["name"]) for t in tags)

    def _find_recurring_pattern(self, task: Dict[str, Any]) -> Optional[Tuple[str, dict]]:
        """Finds the recurring pattern from a task's tags."""
        tags = task.get("properties", {}).get("Tag", {}).get("multi_select", [])
        for tag in tags:
            name = tag.get("name", "")
            if m := RECURRING_RELATIVE_PATTERN.match(name):
                return "relative", {"count": int(m.group(1)), "unit": m.group(2)}
            if m := RECURRING_WEEKLY_PATTERN.match(name):
                return "weekly", {"weekday": WEEKDAY_MAP.get(m.group(1).lower())}
            if m := RECURRING_MONTHLY_PATTERN.match(name):
                return "monthly", {"day": int(m.group(1))}
        return None

    def _handle_recurring_task(self, task: Dict[str, Any]):
        """Resets a recurring task's due date and status."""
        pattern_info = self._find_recurring_pattern(task)
        if not pattern_info:
            logger.warning(f"No recurring pattern found for task {task['id']}. Skipping reset.")
            return

        pattern_type, pattern_details = pattern_info
        next_date = self._calculate_next_date(pattern_type, pattern_details)
        if not next_date:
            logger.error(f"Could not calculate next date for task {task['id']}")
            return

        properties_to_update = {
            "Status": {"status": {"name": "ToDo"}},
            "Done": {"checkbox": False},
            "DoDate": {"date": {"start": next_date.strftime("%Y-%m-%d")}},
            "DoneDate": {"date": None}
        }
        self.notion.update_page(page_id=task["id"], properties=properties_to_update)
        logger.info(f"Reset recurring task {task['id']}")

    def _calculate_next_date(self, pattern_type: str, details: dict) -> Optional[datetime]:
        """Calculates the next occurrence date for a recurring task."""
        today = datetime.now()
        if pattern_type == "relative":
            count, unit = details.get("count"), details.get("unit")
            if count is None or unit is None: return None
            if unit == 'd': return today + timedelta(days=count)
            if unit == 'w': return today + timedelta(weeks=count)
            if unit == 'm': return today + relativedelta(months=count)
        elif pattern_type == "weekly":
            target_weekday = details.get("weekday")
            if target_weekday is None: return None
            days_ahead = target_weekday - today.weekday()
            if days_ahead <= 0: days_ahead += 7
            return today + timedelta(days=days_ahead)
        elif pattern_type == "monthly":
            day = details.get("day")
            if day is None: return None
            next_month = today.month + 1 if today.day >= day else today.month
            year = today.year + (next_month // 13)
            next_month = next_month % 12 or 12
            return datetime(year, next_month, day)
        return None

    def _filter_safe_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recursively removes unsupported blocks and problematic keys."""
        safe_blocks = []
        for block in blocks:
            block_type = block.get("type")

            # Skip unsupported blocks entirely
            if block_type in ["unsupported", "child_database"]:
                continue

            # Create a clean copy of the block
            safe_block = block.copy()
            for key in ["id", "created_by", "created_time", "last_edited_by", "last_edited_time", "parent"]:
                safe_block.pop(key, None)

            # Handle specific block types that can cause validation errors
            if block_type == "image":
                image_data = safe_block.get("image")
                if not image_data:
                    logger.warning(f"Skipping image block with no image data.")
                    continue

                image_type = image_data.get("type")
                if image_type == "external":
                    # Ensure the external image has a URL
                    if not image_data.get("external", {}).get("url"):
                        logger.warning(f"Skipping external image block with no URL.")
                        continue
                elif image_type == "file":
                    # File-based images have URLs that expire. It's safest to skip them when copying.
                    logger.warning(f"Skipping file-based image to avoid expired URL issues.")
                    continue
                else:
                    # If the image block is malformed or has an unknown type, skip it.
                    logger.warning(f"Skipping malformed or unknown image block type.")
                    continue

            # Recursively filter children of blocks that have them
            if block.get("has_children"):
                child_blocks = self.notion.get_all_block_children(block["id"])
                # The API expects the children to be nested inside the block type key
                if child_blocks:
                    safe_block[block_type]["children"] = self._filter_safe_blocks(child_blocks)
                elif block_type in ["column_list", "synced_block"]:
                    # If a column_list or synced_block has no children, it's invalid.
                    logger.warning(f"Skipping empty {block_type}: {block['id']}")
                    continue

            safe_blocks.append(safe_block)
        return safe_blocks

    def _create_tasks_from_open_todos(self, task: Dict[str, Any], blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Creates new tasks from uncompleted to-do blocks."""
        created_tasks = []
        open_todos = [b for b in blocks if b.get("type") == "to_do" and not b.get("to_do", {}).get("checked")]

        for todo_block in open_todos:
            todo_text = "".join(rt.get("plain_text", "") for rt in todo_block.get("to_do", {}).get("rich_text", []))
            if not todo_text: continue

            new_task_props = self._map_task_to_notebook_properties(task)
            new_task_props["Name"] = {"title": [{"text": {"content": todo_text}}]}
            new_task_props["Status"] = {"status": {"name": "ToDo"}}
            new_task_props.pop("DoneDate", None)
            new_task_props.pop("DoDate", None)

            if self._is_recurring_task(task):
                pattern_info = self._find_recurring_pattern(task)
                if pattern_info:
                    pattern_type, pattern_details = pattern_info
                    next_date = self._calculate_next_date(pattern_type, pattern_details)
                    if next_date:
                        new_task_props["DoDate"] = {"date": {"start": next_date.strftime('%Y-%m-%d')}}

            new_task = self.notion.create_page(
                parent_id=self.task_database_id,
                properties=new_task_props,
                is_database=True
            )
            created_tasks.append(new_task)
            logger.info(f"Created new task {new_task['id']} from open to-do: '{todo_text}'")

        return created_tasks

def main():
    """Main script execution."""
    try:
        if not all([NOTION_API_TOKEN, TASK_DATABASE_ID, NOTEBOOK_DATABASE_ID]):
            print("Error: Missing one or more required environment variables.")
            return

        task_service = TaskService()
        print("Processing all completed tasks...")
        recurring, non_recurring = task_service.process_all_completed_tasks()

        print(f"\nProcessed {len(recurring)} recurring tasks.")
        print(f"Processed {len(non_recurring)} non-recurring tasks.")
        total = len(recurring) + len(non_recurring)
        print(f"Total tasks processed: {total}")

        if total > 0:
            print("\n--- Detailed Results ---")
            if recurring:
                print("\nRecurring Tasks (Reset):")
                for r in recurring: print(f"  - Task {r['original_task_id']} moved to Notebook {r['new_notebook_page_id']}")
            if non_recurring:
                print("\nNon-Recurring Tasks (Archived):")
                for nr in non_recurring: print(f"  - Task {nr['original_task_id']} moved to Notebook {nr['new_notebook_page_id']}")
        
        print("\nTask processing complete.")

    except Exception as e:
        logger.error(f"An unexpected error occurred in main execution: {e}", exc_info=True)
        print(f"An unexpected error occurred. See logs for details.")

if __name__ == "__main__":
    main()
