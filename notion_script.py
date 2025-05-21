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

# Using the actual database IDs from the schema
# TasksDB ID: a3b073d5b30d48089bd9eb62ed180e15
# Notebook ID: 1f5d6c20dc718089ae02eea25fb480f5
TASK_DATABASE_ID = os.getenv("TASK_DATABASE_ID", "a3b073d5b30d48089bd9eb62ed180e15")
NOTEBOOK_DATABASE_ID = os.getenv("NOTEBOOK_DATABASE_ID", "1f5d6c20dc718089ae02eea25fb480f5")

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
                clean_properties["Title"] = {
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
        
        # Validate environment variables
        if not NOTION_API_TOKEN:
            raise ValueError("NOTION_API_TOKEN must be set in environment variables")
            
        if not TASK_DATABASE_ID:
            raise ValueError("TASK_DATABASE_ID must be set in environment variables")
            
        if not NOTEBOOK_DATABASE_ID:
            raise ValueError("NOTEBOOK_DATABASE_ID must be set in environment variables")
        
        self.task_database_id = TASK_DATABASE_ID
        self.notebook_database_id = NOTEBOOK_DATABASE_ID
        
        # Validate database access
        self._validate_database_access()
        
    def _validate_database_access(self):
        """Validate that the databases exist and are accessible."""
        try:
            # Try to query task database
            logger.info(f"Validating access to task database: {self.task_database_id}")
            self.notion.query_database(
                database_id=self.task_database_id,
                filter_dict={}
                # Not using sorts since we're just validating access
            )
            logger.info("Task database access validated successfully")
            
            # Try to query notebook database
            logger.info(f"Validating access to notebook database: {self.notebook_database_id}")
            self.notion.query_database(
                database_id=self.notebook_database_id,
                filter_dict={}
                # Not using sorts since we're just validating access
            )
            logger.info("Notebook database access validated successfully")
            
        except Exception as e:
            error_msg = str(e)
            if "Could not find database" in error_msg:
                raise ValueError(f"Database not found or integration doesn't have access. Please check your database IDs and make sure your Notion integration has been added to both databases. Error: {error_msg}")
            else:
                raise ValueError(f"Error validating database access: {error_msg}")

    def move_task_to_notebook(self, task_id: str) -> Dict[str, Any]:
        """
        Move a completed task from the Tasks database to the Notebook database.
        Also extracts any uncompleted todos and creates new tasks for them.
        
        Args:
            task_id: ID of the task to move
            
        Returns:
            Dictionary with the original task ID, new notebook page ID,
            and any new tasks created from uncompleted todos
        """
        # Retrieve the task from Notion
        task = self.notion.get_page(task_id)
        
        # Check if the task is from the right database
        parent_db_id = task.get("parent", {}).get("database_id", "")
        # Normalize both IDs by removing hyphens before comparing
        normalized_parent_id = parent_db_id.replace("-", "")
        normalized_task_db_id = self.task_database_id.replace("-", "")
        
        logger.debug(f"Comparing database IDs - Parent: {parent_db_id} ({normalized_parent_id}), Task DB: {self.task_database_id} ({normalized_task_db_id})")
        
        if normalized_parent_id != normalized_task_db_id:
            logger.warning(f"Task {task_id} is not from the task database")
            raise ValueError(f"Task {task_id} is not from the task database")
        
        # Check if the task status is "Done" using the Status property ID
        status_id = "293591cd-faf9-4508-a72d-267ba96420d8"  # ID for the Status property
        status = task.get("properties", {}).get(status_id, {}).get("status", {}).get("name", "")
        
        logger.info(f"Task {task_id} status: {status}")
        
        # Only process tasks that have Status set to "Done"
        if status != "Done":
            logger.info(f"Task {task_id} does not have status 'Done', skipping")
            return {"status": "skipped", "message": "Task status is not 'Done'", "original_task_id": task_id}
        
        # Check if this is a recurring task
        is_recurring = self._is_recurring_task(task)
        
        # Copy all the task's content blocks
        logger.info(f"Getting all block children for task {task_id}")
        blocks = self.notion.get_all_block_children(task_id)
        logger.info(f"Received {len(blocks)} blocks from Notion API for task {task_id}")
        
        # Check for uncompleted todos in the task content and create new tasks for them
        created_todo_tasks = []
        if blocks:
            print(f"DIRECT PRINT: About to call _extract_open_todos_from_task for task {task_id}")
            logger.info(f"Calling _extract_open_todos_from_task for task {task_id} with {len(blocks)} blocks")
            
            # Extract uncompleted todos from task content
            open_todos = self._extract_open_todos_from_task(task, blocks)
            
            print(f"DIRECT PRINT: After calling _extract_open_todos_from_task, got {len(open_todos)} todos")
            logger.info(f"_extract_open_todos_from_task returned {len(open_todos)} open todos")
            
            # Create new tasks for any open todos
            if open_todos:
                task_title = self._get_title_from_page(task)
                logger.info(f"Creating {len(open_todos)} new tasks for open todos from '{task_title}'")
                
                for todo_item in open_todos:
                    try:
                        # Create a new task in the task database
                        new_task = self.notion.create_page(
                            parent_id=self.task_database_id,
                            properties=todo_item["properties"],
                            is_database=True
                        )
                        
                        created_todo_tasks.append({
                            "todo_text": todo_item["todo_text"],
                            "task_id": new_task["id"]
                        })
                        
                        logger.info(f"Created new task: '{todo_item['todo_text']}'")
                    except Exception as e:
                        logger.error(f"Error creating task for todo '{todo_item['todo_text']}': {e}")
        
        # Convert task properties to notebook properties
        notebook_properties = self._map_task_to_notebook_properties(task)
        
        # Create new page in notebook database with the mapped properties and content
        new_page = self.notion.create_page(
            parent_id=self.notebook_database_id,
            properties=notebook_properties,
            is_database=True,
            children=blocks
        )
        
        # Handle the original task based on whether it's recurring or not
        if is_recurring:
            # Reset the task for the next occurrence
            updated_task = self._handle_recurring_task(task)
            logger.info(f"Reset recurring task {task_id} for next occurrence")
        else:
            # Archive the original task
            self.notion.update_page(
                page_id=task_id,
                properties={
                    "Status": {
                        "status": {
                            "name": "Archived"
                        }
                    }
                },
                archived=False  # Not actually archiving in Notion, just updating status
            )
            logger.info(f"Archived non-recurring task {task_id}")
        
        result = {
            "original_task_id": task_id,
            "new_notebook_page_id": new_page["id"]
        }
        
        # Add information about created todo tasks if any
        if created_todo_tasks:
            result["created_todo_tasks"] = created_todo_tasks
            
        return result
    
    def process_all_completed_tasks(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process all tasks marked with 'Done' status.
        Identifies recurring and non-recurring tasks, then processes them accordingly.
        
        Returns:
            Tuple of (recurring_results, non_recurring_results)
        """
        # Find all tasks with 'Done' status using the property ID
        status_id = "293591cd-faf9-4508-a72d-267ba96420d8"  # ID for the Status property
        
        filter_dict = {
            "property": status_id,
            "status": {
                "equals": "Done"
            }
        }
        
        logger.info(f"Filtering tasks with Status='Done' using property ID: {status_id}")
        
        # Get all tasks with Done status
        done_tasks = self.notion.query_database(
            database_id=self.task_database_id,
            filter_dict=filter_dict
        )
        
        logger.info(f"Found {len(done_tasks)} tasks with Status='Done'")
        
        # Debug log the task IDs and their status
        for task in done_tasks:
            task_id = task.get("id", "unknown")
            status = task.get("properties", {}).get(status_id, {}).get("status", {}).get("name", "unknown")
            logger.info(f"Found Done task: ID={task_id}, Status={status}")

        
        recurring_results = []
        non_recurring_results = []
        
        # Process each task based on whether it's recurring or not
        for task in done_tasks:
            task_id = task["id"]
            try:
                # Skip re-checking the status since we already filtered for Done tasks
                logger.info(f"Processing task {task_id} (already filtered as 'Done')")
                
                # Check if the task is recurring
                is_recurring = self._is_recurring_task(task)
                logger.info(f"Task {task_id} is_recurring: {is_recurring}")
                
                # Copy all the task's content blocks
                blocks = self.notion.get_all_block_children(task_id)
                
                # Extract and process unchecked todos from the task content
                if blocks:
                    print(f"===== Processing {len(blocks)} blocks for task {task_id} to extract unchecked todos =====")
                    open_todos = self._extract_open_todos_from_task(task, blocks)
                    print(f"===== Found {len(open_todos)} unchecked todos in task {task_id} =====")
                    
                    # Create new tasks for any unchecked todos
                    if open_todos:
                        task_title = self._get_title_from_page(task)
                        logger.info(f"Creating {len(open_todos)} new tasks for open todos from '{task_title}'")
                        
                        created_todo_ids = []
                        
                        for todo_item in open_todos:
                            try:
                                # Create a new task in the task database
                                new_task = self.notion.create_page(
                                    parent_id=self.task_database_id,
                                    properties=todo_item["properties"],
                                    is_database=True
                                )
                                
                                todo_id = new_task["id"]
                                created_todo_ids.append({
                                    "block_id": todo_item["block_id"],
                                    "task_id": todo_id,
                                    "todo_text": todo_item["todo_text"]
                                })
                                
                                logger.info(f"Created new task for todo: '{todo_item['todo_text']}'")
                                logger.info(f"New task ID: {todo_id}")
                            except Exception as e:
                                logger.error(f"Error creating task for todo '{todo_item['todo_text']}': {e}")
                        
                        # Update the original todo blocks to mark them as moved BEFORE copying to notebook
                        updated_block_ids = []
                        for todo_info in created_todo_ids:
                            try:
                                # Update the original todo block with strikethrough formatting and "moved to tasks" prefix
                                original_text = todo_info["todo_text"]
                                block_id = todo_info["block_id"]
                                
                                # Create formatted text with "moved to tasks" prefix and strikethrough
                                updated_rich_text = [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": "moved to tasks: ",
                                            "link": None
                                        },
                                        "annotations": {
                                            "bold": True,
                                            "italic": False,
                                            "strikethrough": False,
                                            "underline": False,
                                            "code": False,
                                            "color": "default"
                                        },
                                        "plain_text": "moved to tasks: "
                                    },
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": original_text,
                                            "link": None
                                        },
                                        "annotations": {
                                            "bold": False,
                                            "italic": False,
                                            "strikethrough": True,
                                            "underline": False,
                                            "code": False,
                                            "color": "default"
                                        },
                                        "plain_text": original_text
                                    }
                                ]
                                
                                # Update the block in Notion
                                update_url = f"{self.notion.base_url}/blocks/{block_id}"
                                update_payload = {
                                    "to_do": {
                                        "rich_text": updated_rich_text,
                                        "checked": True,
                                        "color": "default"
                                    }
                                }
                                
                                response = requests.patch(
                                    update_url, 
                                    headers=self.notion.headers, 
                                    json=update_payload
                                )
                                
                                if response.status_code == 200:
                                    logger.info(f"Updated original todo block to mark as moved: '{original_text}'")
                                    updated_block_ids.append(block_id)
                                else:
                                    logger.error(f"Failed to update original todo block: {response.text}")
                            except Exception as e:
                                logger.error(f"Error updating original todo block: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                        
                        # If we updated any blocks, we need to re-fetch the blocks to get the updated content
                        if updated_block_ids:
                            logger.info(f"Re-fetching blocks after marking todos as moved")
                            blocks = self.notion.get_all_block_children(task_id)
                
                # Convert task properties to notebook properties
                notebook_properties = self._map_task_to_notebook_properties(task)
                
                # Get the task title for API
                task_title = self._get_title_from_page(task)
                logger.info(f"Passing task title to API: '{task_title}'")
                
                # Create new page in notebook database with the mapped properties and content
                new_page = self.notion.create_page(
                    parent_id=self.notebook_database_id,
                    properties=notebook_properties,
                    is_database=True,
                    children=blocks if blocks else None,
                    title_for_api=task_title
                )
                
                # Verify that the task data was properly transferred
                self._verify_data_transfer(task, new_page, notebook_properties)
                
                # Handle the original task based on whether it's recurring or not
                if is_recurring:
                    # Reset the task for the next occurrence
                    updated_task = self._handle_recurring_task(task)
                    logger.info(f"Reset recurring task {task_id} for next occurrence")
                else:
                    # Archive the original task
                    self.notion.update_page(
                        page_id=task_id,
                        properties={
                            status_id: {
                                "status": {
                                    "name": "Archived"
                                }
                            }
                        },
                        archived=False  # Not actually archiving in Notion, just updating status
                    )
                    logger.info(f"Archived non-recurring task {task_id}")
                
                result = {
                    "original_task_id": task_id,
                    "new_notebook_page_id": new_page["id"]
                }
                
                # Add the result to the appropriate list
                if is_recurring:
                    recurring_results.append(result)
                else:
                    non_recurring_results.append(result)
                    
            except Exception as e:
                logger.error(f"Error processing task {task_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        return recurring_results, non_recurring_results
    
    # Keeping these methods for backward compatibility
    def process_recurring_tasks(self) -> List[Dict[str, Any]]:
        """
        Process all recurring tasks that are marked as Done.
        Moves them to notebook and resets them for the next occurrence.
        
        Returns:
            List of task IDs that were processed
        """
        recurring_results, _ = self.process_all_completed_tasks()
        return recurring_results
        
    def process_completed_tasks(self, archive: bool = True) -> List[Dict[str, Any]]:
        """
        Process all completed non-recurring tasks.
        Moves them to notebook and archives the originals if archive is True.
        
        Args:
            archive: Whether to archive the original task after moving
            
        Returns:
            List of task IDs that were processed
        """
        _, non_recurring_results = self.process_all_completed_tasks()
        return non_recurring_results
        
    def _map_task_to_notebook_properties(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map task properties to notebook properties based on property IDs and types.
        
        Args:
            task: The task page from Notion
            
        Returns:
            Dictionary of properties formatted for the notebook database
        """
        task_properties = task.get("properties", {})
        notebook_properties = {}
        
        # Task database property IDs from API schema
        # These are the actual IDs that Notion uses internally
        # Using IDs makes the integration stable even if property names change in the UI
        taskdb_property_ids = {
            # Property name: Property ID (from raw_api_response in schema)
            "title": "title",                                # Title is special in Notion API
            "Status": "293591cd-faf9-4508-a72d-267ba96420d8", # Status property ID
            "Tag": "Bh%5CH",                               # Tag property ID
            "Priority": "F%3A%3BP",                         # Priority property ID
            "Type": "F%40%5B%3A",                         # Type property ID 
            "Location": "JJ%60S",                          # Location property ID
            "DoneDate": "x~tu",                           # DoneDate property ID
            "DoDate": "d%60BM",                           # DoDate property ID
            "Project": "a~%7Cl",                           # Project relation property ID
            "People": "kNFv",                             # People property ID
            "Done": "n%3D%7BP",                           # Done property ID
            "URL": "yWt%40",                              # URL property ID
            "Time": "~MZe",                              # Time property ID
            "Cost": "e75003f5-a9dc-4d80-9388-2828842b6e73", # Cost property ID
        }
        
        # Notebook database property IDs from API schema
        # These are the actual IDs that Notion uses internally
        # Using the correct IDs ensures stability even if property names change
        notebookdb_property_ids = {
            # Property name: Property ID (from raw_api_response in schema)
            "title": "title",                                # Title is special in Notion API
            "Status": "6225b47e-e2ee-4c80-b088-805ead975486", # Status property ID
            "Tag": "Bh%5CH",                               # Tag property ID
            "Priority": "F%3A%3BP",                         # Priority property ID
            "Type": "F%40%5B%3A",                         # Type property ID
            "Location": "JJ%60S",                          # Location property ID
            "DoneDate": "x~tu",                           # DoneDate property ID
            "DoDate": "d%60BM",                           # DoDate property ID
            "Project": "a~%7Cl",                           # Project relation property ID
            "People": "kNFv",                             # People property ID
            "Done": "b5ecd428-a8f4-4cc1-b739-cde15798dc5e", # Done property ID
            "URL": "yWt%40",                              # URL property ID
            "Time": "~MZe",                              # Time property ID
            "Cost": "e75003f5-a9dc-4d80-9388-2828842b6e73", # Cost property ID
        }
        
        # URL-decode the property IDs for use in the API
        decoded_notebookdb_property_ids = {}
        for prop_name, prop_id in notebookdb_property_ids.items():
            # URL-decode the property ID
            decoded_prop_id = urllib.parse.unquote(prop_id)
            decoded_notebookdb_property_ids[prop_name] = decoded_prop_id
            
            # Log the original and decoded IDs for debugging
            if prop_id != decoded_prop_id:
                logger.info(f"Decoded property ID for {prop_name}: {prop_id} -> {decoded_prop_id}")
        
        # Important: When CREATING pages with the Notion API, we must use property NAMES, not IDs
        # However, we keep the ID mapping for reference and potential future use cases
        # For READ operations, we can use either
        # For WRITE operations like page creation, we MUST use property names
        property_mapping = {
            # Task property name: Notebook property name
            "title": "title",         # Title is special
            "Status": "Status",       # Use name for API compatibility
            "Tag": "Tag",             # Use name for API compatibility
            "Priority": "Priority",   # Use name for API compatibility
            "Type": "Type",           # Use name for API compatibility
            "Location": "Location",   # Use name for API compatibility
            "DoneDate": "DoneDate",   # Use name for API compatibility
            "DoDate": "DoDate",       # Use name for API compatibility
            "Project": "Project",     # Use name for API compatibility 
            "People": "People",       # Use name for API compatibility
            "Done": "Done",           # Use name for API compatibility
            "URL": "URL",             # Use name for API compatibility
            "Time": "Time",           # Use name for API compatibility
            "Cost": "Cost",           # Use name for API compatibility
        }
        
        # Extract the plain text title from the task
        title_value = ""
        title_property = task_properties.get("title", {})
        
        if title_property.get("title"):
            title_content = title_property.get("title", [])
            # Extract plain text from title content
            title_value = "".join([item.get("plain_text", "") for item in title_content])
            
        # Set the notebook title - in Notion API, the title field is special
        # The title property must always use the key "title" regardless of the actual property ID
        # This is a known quirk/requirement of the Notion API 
        if title_value:
            # According to Notion API docs, the title field must be "title" (lowercase)
            # The title field ID doesn't matter - it must use the key "title"
            notebook_properties["title"] = {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title_value}
                    }
                ]
            }
            logger.info(f"Setting title to: '{title_value}' using Notion API convention")
            logger.info("NOTE: Title field always uses the key 'title' in the API regardless of its actual ID")
            
            # Print debug info about notebook properties
            logger.info(f"Title property JSON: {json.dumps(notebook_properties['title'])}")
            
            # For Notion API debugging - dump request JSON
            debug_props = notebook_properties.copy()
            debug_props.pop('title', None)
            logger.info(f"Other properties: {list(debug_props.keys())}")
            
            # Hard-set the title directly in the API call parameters
            self.title_for_api = title_value
        
        # First, we collect properties by name from the task
        # This helps us match by name rather than ID
        task_properties_by_name = {}
        property_types = {}
        
        # Loop through all properties and extract their names
        for prop_id, prop_data in task_properties.items():
            prop_type = prop_data.get("type")
            
            # Skip non-transferable types
            if prop_type in ["button", "formula", "rollup"]:
                continue
            
            # Handle title property specially
            if prop_id == "title":
                if prop_data.get("title"):
                    # Make sure the title is properly mapped
                    logger.info(f"Setting title property with value: {prop_data.get('title')}")
                    notebook_properties["title"] = {
                        "title": prop_data.get("title", [])
                    }
                continue
            
            # Status property (extract status name)
            if prop_type == "status":
                status_name = prop_data.get("status", {}).get("name", "")
                task_properties_by_name["Status"] = {"type": prop_type, "value": status_name, "raw": prop_data}
                property_types["Status"] = prop_type
                
            # Tag property (multi-select)
            elif prop_type == "multi_select" and "Tag" in prop_id:
                tags = prop_data.get("multi_select", [])
                task_properties_by_name["Tag"] = {"type": prop_type, "value": tags, "raw": prop_data}
                property_types["Tag"] = prop_type
            
            # Priority property (select)
            elif prop_type == "select" and "Priority" in prop_id:
                priority = prop_data.get("select")
                task_properties_by_name["Priority"] = {"type": prop_type, "value": priority, "raw": prop_data}
                property_types["Priority"] = prop_type
            
            # Type property (select)
            elif prop_type == "select" and "Type" in prop_id:
                type_val = prop_data.get("select")
                task_properties_by_name["Type"] = {"type": prop_type, "value": type_val, "raw": prop_data}
                property_types["Type"] = prop_type
            
            # Location property (select)
            elif prop_type == "select" and "Location" in prop_id:
                location = prop_data.get("select")
                task_properties_by_name["Location"] = {"type": prop_type, "value": location, "raw": prop_data}
                property_types["Location"] = prop_type
            
            # Date properties
            elif prop_type == "date":
                if "Done" in prop_id:
                    task_properties_by_name["DoneDate"] = {"type": prop_type, "value": prop_data.get("date"), "raw": prop_data}
                    property_types["DoneDate"] = prop_type
                elif "Do" in prop_id:
                    task_properties_by_name["DoDate"] = {"type": prop_type, "value": prop_data.get("date"), "raw": prop_data}
                    property_types["DoDate"] = prop_type
            
            # People property
            elif prop_type == "people":
                people = prop_data.get("people", [])
                task_properties_by_name["People"] = {"type": prop_type, "value": people, "raw": prop_data}
                property_types["People"] = prop_type
            
            # Done checkbox
            elif prop_type == "checkbox" and "Done" in prop_id:
                done = prop_data.get("checkbox", False)
                task_properties_by_name["Done"] = {"type": prop_type, "value": done, "raw": prop_data}
                property_types["Done"] = prop_type
            
            # Project relation property
            elif prop_type == "relation":
                relations = prop_data.get("relation", [])
                
                # Project is a special case that requires careful handling
                if "Project" in prop_id or "project" in prop_id.lower():
                    if relations:
                        logger.info(f"Found Project relation with {len(relations)} connected items: {relations}")
                        task_properties_by_name["Project"] = {"type": prop_type, "value": relations, "raw": prop_data}
                        property_types["Project"] = prop_type
                        
                        # Directly set the Project relation in notebook properties
                        notebook_properties["Project"] = {
                            "relation": relations
                        }
                        logger.info(f"Directly setting Project relation with {len(relations)} items")
                    else:
                        logger.info("Project relation found but no connected items")
            
            # URL property
            elif prop_type == "url":
                url = prop_data.get("url", "")
                task_properties_by_name["URL"] = {"type": prop_type, "value": url, "raw": prop_data}
                property_types["URL"] = prop_type
            
            # Time property (number)
            elif prop_type == "number" and "Time" in prop_id:
                time_val = prop_data.get("number")
                task_properties_by_name["Time"] = {"type": prop_type, "value": time_val, "raw": prop_data}
                property_types["Time"] = prop_type
            
            # Cost property (number)
            elif prop_type == "number" and "Cost" in prop_id:
                cost = prop_data.get("number")
                task_properties_by_name["Cost"] = {"type": prop_type, "value": cost, "raw": prop_data}
                property_types["Cost"] = prop_type
        
        # Now build notebook properties using property IDs for maximum stability
        logger.info(f"Mapping properties from task to notebook using property IDs")
        # Log all available property names in the task for debugging
        logger.info(f"Available task properties: {list(task_properties.keys())}")
        
        for task_prop_name, notebook_prop_id in property_mapping.items():
            if task_prop_name == "title":
                continue  # Already handled title
            
            # Check if this property name exists in the task
            if task_prop_name not in task_properties:
                logger.info(f"Property '{task_prop_name}' not found in task")
                continue  # Skip properties not found
            
            # Get the property data and type
            prop_data = task_properties[task_prop_name]
            prop_type = prop_data.get("type")
            
            logger.info(f"Mapping {task_prop_name} ({prop_type}) to notebook property ID '{notebook_prop_id}'")
            
            # When creating pages with the Notion API, we must always use property NAMES (not IDs)
            # After reviewing the Notion API documentation and testing, we've found that page creation
            # requires property names as keys in the payload
            prop_key = property_mapping[task_prop_name]
            
            # Extract values based on property type
            if prop_type == "status":
                value = prop_data.get("status", {}).get("name", "")
                if value:
                    notebook_properties[prop_key] = {"status": {"name": value}}
                    logger.info(f"Set status property '{prop_key}' to '{value}'")
                    
            elif prop_type == "select":
                value = prop_data.get("select")
                if value:
                    notebook_properties[prop_key] = {"select": value}
                    
            elif prop_type == "multi_select":
                values = prop_data.get("multi_select", [])
                if values:
                    notebook_properties[prop_key] = {"multi_select": values}
                    
            elif prop_type == "date":
                value = prop_data.get("date")
                if value:
                    notebook_properties[prop_key] = {"date": value}
                    
            elif prop_type == "checkbox":
                value = prop_data.get("checkbox", False)
                notebook_properties[prop_key] = {"checkbox": value}
                
            elif prop_type == "url":
                value = prop_data.get("url", "")
                if value:
                    notebook_properties[prop_key] = {"url": value}
                    
            elif prop_type == "number":
                value = prop_data.get("number")
                if value is not None:
                    notebook_properties[prop_key] = {"number": value}
                    
            elif prop_type == "relation":
                relations = prop_data.get("relation", [])
                if relations:
                    # Special handling for Project relation
                    if task_prop_name == "Project":
                        logger.info(f"Found Project relation with {len(relations)} connected items: {relations}")
                    notebook_properties[prop_key] = {"relation": relations}
                else:
                    logger.info(f"{task_prop_name} relation found but no connected items")
                    
            elif prop_type == "people":
                people = prop_data.get("people", [])
                if people:
                    notebook_properties[prop_key] = {"people": people}
            
            # Rich text handling (not included in the property_id_map)
            if prop_type == "rich_text" and "rich_text" in prop_data:
                rich_text = prop_data.get("rich_text", [])
                if rich_text:
                    notebook_properties[notebook_prop_name] = {"rich_text": rich_text}
        
        # Set status to Done if not already included
        if "Status" not in notebook_properties:
            notebook_properties["Status"] = {
                "status": {
                    "name": "Done"
                }
            }
            logger.info("Setting default Status='Done'")
        
        # Set DoneDate if not already included
        if "DoneDate" not in notebook_properties:
            current_date = datetime.now().strftime("%Y-%m-%d")
            notebook_properties["DoneDate"] = {
                "date": {
                    "start": current_date
                }
            }
            logger.info(f"Setting default DoneDate={current_date}")
            
        # Set Done checkbox if not already included
        if "Done" not in notebook_properties:
            notebook_properties["Done"] = {
                "checkbox": True
            }
            logger.info("Setting default Done=True")
            
        logger.info(f"Final notebook properties:\n{json.dumps(notebook_properties, indent=2)}")
        
        return notebook_properties
    
    def _is_recurring_task(self, task: Dict[str, Any]) -> bool:
        """
        Check if a task is recurring based on its tags.
        
        Args:
            task: The task page from Notion
            
        Returns:
            True if the task is recurring, False otherwise
        """
        # Check if the Recurring formula property exists and is true
        properties = task.get("properties", {})
        recurring_prop = properties.get("Recurring", {})
        if recurring_prop.get("type") == "formula" and recurring_prop.get("formula", {}).get("checkbox") == True:
            return True
            
        # Check tags for recurring patterns
        tags = properties.get("Tag", {}).get("multi_select", [])
        for tag in tags:
            tag_name = tag.get("name", "")
            if any(pattern.match(tag_name) for pattern in [
                RECURRING_RELATIVE_PATTERN,
                RECURRING_WEEKLY_PATTERN,
                RECURRING_MONTHLY_PATTERN
            ]):
                return True
                
        return False
    
    def _find_recurring_pattern(self, task: Dict[str, Any]) -> Tuple[Optional[str], Optional[dict]]:
        """
        Find the recurring pattern in a task's tags.
        
        Args:
            task: The task page from Notion
            
        Returns:
            Tuple of (pattern type, pattern details)
        """
        tags = task.get("properties", {}).get("Tag", {}).get("multi_select", [])
        for tag in tags:
            tag_name = tag.get("name", "")
            
            # Check for relative recurring pattern (e.g., rec-2w)
            relative_match = RECURRING_RELATIVE_PATTERN.match(tag_name)
            if relative_match:
                count, unit = relative_match.groups()
                return "relative", {"count": int(count), "unit": unit}
                
            # Check for weekly recurring pattern (e.g., rec-weekly-mon)
            weekly_match = RECURRING_WEEKLY_PATTERN.match(tag_name)
            if weekly_match:
                weekday = weekly_match.group(1)
                if weekday in WEEKDAY_MAP:
                    return "weekly", {"weekday": WEEKDAY_MAP[weekday]}
                    
            # Check for monthly recurring pattern (e.g., rec-monthly-15)
            monthly_match = RECURRING_MONTHLY_PATTERN.match(tag_name)
            if monthly_match:
                day = monthly_match.group(1)
                return "monthly", {"day": int(day)}
                
        return None, None
    
    def _handle_recurring_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a recurring task by resetting its due date and status.
        
        Args:
            task: The task page from Notion
            
        Returns:
            The updated task
        """
        pattern_type, pattern_details = self._find_recurring_pattern(task)
        
        if not pattern_type or not pattern_details:
            logger.warning(f"Could not find recurring pattern for task {task['id']}")
            return task
            
        # Calculate the next occurrence date
        next_date = self._calculate_next_date(pattern_type, pattern_details)
        
        # Update the task with the new date and reset status
        updated_task = self.notion.update_page(
            page_id=task["id"],
            properties={
                "Status": {
                    "status": {
                        "name": "ToDo"
                    }
                },
                "Done": {
                    "checkbox": False
                },
                "DoDate": {
                    "date": {
                        "start": next_date.strftime("%Y-%m-%d")
                    }
                },
                "DoneDate": {
                    "date": None
                }
            }
        )
        
        return updated_task
    
    def _extract_open_todos_from_task(self, task: Dict[str, Any], blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract uncompleted todos from the task's content blocks.
        
        Args:
            task: The task page from Notion
            blocks: The task's content blocks
            
        Returns:
            List of dictionaries with todo text and new task properties
        """
        # Direct print to verify this method is called
        print("======== _extract_open_todos_from_task METHOD CALLED ========")
        logger.info("======== _extract_open_todos_from_task METHOD CALLED ========")
        open_todos = []
        task_title = self._get_title_from_page(task)
        task_id = task.get("id", "unknown")
        
        # Direct debugging output - dump the task info
        logger.info(f"EXTRACT: Starting todo extraction for task '{task_title}' (ID: {task_id})")
        logger.info(f"EXTRACT: Found {len(blocks)} blocks to examine")
        
        # Get today's date for the new tasks' DoDate
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Debug log the block structure
        logger.info(f"Analyzing {len(blocks)} blocks in task '{task_title}' (ID: {task_id})")
        if not blocks:
            logger.warning(f"No blocks found in task '{task_title}' (ID: {task_id})")
            return []
            
        block_types = {}
        for i, block in enumerate(blocks):
            block_type = block.get("type", "unknown")
            block_id = block.get("id", "unknown")
            block_types[block_type] = block_types.get(block_type, 0) + 1
            
            # Debug output for each block
            logger.info(f"Block {i+1}/{len(blocks)}: type={block_type}, id={block_id}")
            
            # Dump first 5 blocks completely for inspection
            if i < 5:
                # Use json.dumps to pretty print the block structure
                block_str = json.dumps(block, indent=2, default=str)
                logger.info(f"Block {i+1} structure:\n{block_str}")
            
            # Additional debug for todo blocks
            if block_type == "to_do":
                todo_content = block.get("to_do", {})
                is_checked = todo_content.get("checked", False)
                rich_text = todo_content.get("rich_text", [])
                todo_text = ""
                for text_item in rich_text:
                    todo_text += text_item.get("plain_text", "")
                logger.info(f"  TODO item: '{todo_text}', checked={is_checked}")
        
        # Log summary of block types
        logger.info(f"Block type summary for task '{task_title}': {block_types}")
        
        # Loop through all blocks to find unchecked todo items
        logger.info(f"Examining {len(blocks)} blocks for unchecked todos in task '{task_title}'")
        for i, block in enumerate(blocks):
            block_id = block.get("id", "unknown")
            block_type = block.get("type", "unknown")
            
            # Log basic information about each block
            logger.info(f"Processing block {i+1}/{len(blocks)}: type={block_type}, id={block_id}")
            
            if block_type == "to_do":
                todo_content = block.get("to_do", {})
                is_checked = todo_content.get("checked", False)
                todo_text = ""
                
                # Extract the todo text
                rich_text = todo_content.get("rich_text", [])
                for text_item in rich_text:
                    todo_text += text_item.get("plain_text", "")
                
                # Detailed debugging for the todo item
                logger.info(f"EXTRACT: TODO item found: '{todo_text}', checked={is_checked}")
                
                # Dump the raw todo content for debugging
                logger.info(f"EXTRACT: Raw todo content: {json.dumps(todo_content, indent=2, default=str)}")
                
                # Specific check for the checked field
                if "checked" in todo_content:
                    logger.info(f"EXTRACT: 'checked' field explicitly set to: {todo_content['checked']}")
                else:
                    logger.info(f"EXTRACT: 'checked' field not explicitly present in todo content")
                
                # If the todo is not checked, prepare a new task
                if not is_checked and todo_text.strip():
                    logger.info(f"Processing unchecked todo: '{todo_text.strip()}'")
                    
                    # Create new task properties (copy from original task)
                    new_task_properties = {
                        "title": {
                            "title": [
                                {
                                    "type": "text",
                                    "text": {"content": f"{task_title}: {todo_text.strip()}"}
                                }
                            ]
                        },
                        "Status": {
                            "status": {"name": "ToDo"}
                        },
                        "DoDate": {
                            "date": {"start": today}
                        }
                    }
                    
                    # Copy some properties from the original task if they exist
                    original_properties = task.get("properties", {})
                    
                    # Copy Project relation if it exists
                    if "Project" in original_properties and original_properties["Project"].get("relation"):
                        new_task_properties["Project"] = {
                            "relation": original_properties["Project"]["relation"]
                        }
                    
                    # Copy Priority if it exists
                    if "Priority" in original_properties and original_properties["Priority"].get("select"):
                        new_task_properties["Priority"] = {
                            "select": original_properties["Priority"]["select"]
                        }
                    
                    # Copy Type if it exists
                    if "Type" in original_properties and original_properties["Type"].get("select"):
                        new_task_properties["Type"] = {
                            "select": original_properties["Type"]["select"]
                        }
                    
                    open_todos.append({
                        "todo_text": todo_text.strip(),
                        "properties": new_task_properties,
                        "block_id": block.get("id")
                    })
                    
                    logger.info(f"Found open todo: '{todo_text.strip()}'")
                else:
                    if is_checked:
                        logger.info(f"Skipping checked todo: '{todo_text.strip()}'")
                    elif not todo_text.strip():
                        logger.info(f"Skipping empty todo")
        
        logger.info(f"Found {len(open_todos)} open todos in task '{task_title}'")
        return open_todos
    
    def _verify_data_transfer(self, task: Dict[str, Any], new_page: Dict[str, Any], notebook_properties: Dict[str, Any]) -> bool:
        """
        Verify that the task data was properly transferred to the notebook page.
        Compare original task properties with the mapped notebook properties.
        
        Args:
            task: The original task page from Notion
            new_page: The newly created notebook page
            notebook_properties: The properties mapped for the notebook page
            
        Returns:
            True if the data transfer was successful, False otherwise
        """
        task_id = task.get("id", "unknown")
        notebook_id = new_page.get("id", "unknown")
        logger.info(f"Verifying data transfer from task {task_id} to notebook page {notebook_id}")
        
        # Check title transfer - this is a special case
        task_title = self._get_title_from_page(task)
        notebook_title = self._get_title_from_page(new_page)
        
        # Log the title comparison for debugging
        logger.info(f"Task title: '{task_title}'")
        logger.info(f"Notebook title: '{notebook_title}'")
        
        if task_title and notebook_title:
            if task_title == notebook_title:
                logger.info(f"Title verification: '{task_title}' correctly transferred")
            else:
                logger.warning(f"Title mismatch: Task title '{task_title}' differs from notebook title '{notebook_title}'")
        elif task_title and not notebook_title:
            logger.warning(f"Title missing: Task title '{task_title}' not transferred to notebook")
        elif not task_title and notebook_title:
            logger.info(f"Title added: New title '{notebook_title}' was set in notebook")
        else:
            logger.warning("Both task and notebook are missing titles")

        # Find all project relations
        project_relations_transferred = False
        task_projects = []
        notebook_projects = []
        
        # Check original task project relations
        for prop_name, prop_data in task.get("properties", {}).items():
            if prop_data.get("type") == "relation" and ("Project" in prop_name or "project" in prop_name.lower()):
                relations = prop_data.get("relation", [])
                if relations:
                    task_projects.extend([rel.get("id") for rel in relations])
        
        # Check notebook project relations
        for prop_name, prop_data in new_page.get("properties", {}).items():
            if prop_data.get("type") == "relation" and ("Project" in prop_name or "project" in prop_name.lower()):
                relations = prop_data.get("relation", [])
                if relations:
                    notebook_projects.extend([rel.get("id") for rel in relations])
        
        # Log project relation transfer status
        if task_projects:
            overlap = set(task_projects) & set(notebook_projects)
            if overlap:
                logger.info(f"Project relations transferred: {len(overlap)} of {len(task_projects)}")
                project_relations_transferred = True
            else:
                logger.warning(f"Project relations missing: {len(task_projects)} relations not transferred")
        
        # Verify other properties
        # For Notion API responses, we can't directly compare by property type due to how Notion 
        # represents and returns data. Instead, we'll check for existence of key properties.
        critical_properties = [
            "Status",
            "Done",
            "DoneDate"
        ]
        
        missing_critical_props = []
        for prop in critical_properties:
            if prop not in new_page.get("properties", {}):
                missing_critical_props.append(prop)
        
        if missing_critical_props:
            logger.warning(f"Missing critical properties: {', '.join(missing_critical_props)}")
        else:
            logger.info("All critical properties exist in notebook entry")
            
        # Overall transfer success verdict
        transfer_success = notebook_title and (not missing_critical_props) and (not task_projects or project_relations_transferred)
        
        if transfer_success:
            logger.info("✅ Task successfully transferred to notebook")
        else:
            logger.warning("⚠️ Task transfer had some issues - check warnings above")
            
        return transfer_success

    def _get_title_from_page(self, page: Dict[str, Any]) -> str:
        """
        Extract the title from a page object.
        
        Args:
            page: The Notion page object
            
        Returns:
            The page title as a string
        """
        properties = page.get("properties", {})
        title_value = ""
        
        # First check the regular title field (used in our requests)
        title_prop = properties.get("title", {})
        if title_prop and "title" in title_prop and title_prop["title"]:
            title_items = title_prop["title"]
            title_value = "".join([item.get("plain_text", "") for item in title_items])
            return title_value
        
        # If not found, check alternative title fields
        for title_field in ["Title", "Task", "Name"]:
            title_prop = properties.get(title_field, {})
            if title_prop and "title" in title_prop and title_prop["title"]:
                title_items = title_prop["title"]
                title_value = "".join([item.get("plain_text", "") for item in title_items])
                if title_value:
                    return title_value
        
        return ""
        
    def _calculate_next_date(self, pattern_type: str, pattern_details: Dict[str, Any]) -> datetime:
        """
        Calculate the next date for a recurring task based on the pattern.
        
        Args:
            pattern_type: Type of pattern (relative, weekly, monthly)
            pattern_details: Details of the pattern
            
        Returns:
            Next occurrence date as a datetime object
        """
        today = datetime.now()
        
        if pattern_type == "relative":
            count = pattern_details["count"]
            unit = pattern_details["unit"]
            
            if unit == "d":
                return today + timedelta(days=count)
            elif unit == "w":
                return today + timedelta(weeks=count)
            elif unit == "m":
                # Approximate months as 30 days
                return today + relativedelta(months=count)
                
        elif pattern_type == "weekly":
            weekday = pattern_details["weekday"]
            days_ahead = weekday - today.weekday()
            
            # If today is the target weekday or past it, go to next week
            if days_ahead <= 0:
                days_ahead += 7
                
            return today + timedelta(days=days_ahead)
            
        elif pattern_type == "monthly":
            day = pattern_details["day"]
            
            # Set the date to the target day in the next month
            if today.day >= day:
                # Go to next month
                if today.month == 12:
                    next_date = datetime(today.year + 1, 1, day)
                else:
                    next_date = datetime(today.year, today.month + 1, day)
            else:
                # Stay in current month
                next_date = datetime(today.year, today.month, day)
                
            return next_date
            
        # Default fallback: 1 week ahead
        return today + timedelta(weeks=1)
def main():
    """Main script execution."""
    try:
        # Check required environment variables
        if not NOTION_API_TOKEN:
            print("Error: NOTION_API_TOKEN environment variable is not set")
            return
            
        if not TASK_DATABASE_ID:
            print("Error: TASK_DATABASE_ID environment variable is not set")
            return
            
        if not NOTEBOOK_DATABASE_ID:
            print("Error: NOTEBOOK_DATABASE_ID environment variable is not set")
            return
        
        # Initialize the TaskService
        task_service = TaskService()
        
        # Process all completed tasks in one go
        print("Processing all completed tasks...")
        recurring_results, non_recurring_results = task_service.process_all_completed_tasks()
        
        # Print summary of results
        print(f"Processed {len(recurring_results)} recurring tasks")
        print(f"Processed {len(non_recurring_results)} non-recurring tasks")
        
        # Summary
        total_tasks = len(recurring_results) + len(non_recurring_results)
        print(f"\nTotal tasks processed: {total_tasks}")
        
        if total_tasks > 0:
            print("\nDetailed results:")
            # First show recurring tasks
            if recurring_results:
                print("\nRecurring tasks (copied to notebook and reset):")
                for result in recurring_results:
                    original_id = result.get("original_task_id")
                    new_id = result.get("new_notebook_page_id")
                    print(f"  Task {original_id} moved to notebook page {new_id}")
            
            # Then show non-recurring tasks
            if non_recurring_results:
                print("\nNon-recurring tasks (copied to notebook and archived):")
                for result in non_recurring_results:
                    original_id = result.get("original_task_id")
                    new_id = result.get("new_notebook_page_id")
                    print(f"  Task {original_id} moved to notebook page {new_id}")
        
        print("\nTask processing complete")
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
