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
            
        all_results = []
        has_more = True
        next_cursor = None

        while has_more:
            if next_cursor:
                payload["start_cursor"] = next_cursor

            response = requests.post(url, headers=self.headers, json=payload)

            if response.status_code != 200:
                logger.error(f"Error querying database: {response.text}")
                response.raise_for_status()

            data = response.json()
            all_results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")

        return all_results
        
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
        # Note: This part of the logic seems unused given the dynamic title handling elsewhere.
        # It's kept for potential direct calls but should be reviewed.
        if title_for_api:
            logger.warning(f"'title_for_api' is used, which might conflict with dynamic title property handling.")
            if is_database:
                # This assumes the title property is named 'Name', which is a source of errors.
                # The calling function should provide the correctly structured property dictionary.
                logger.info(f"Setting title directly from API parameter: '{title_for_api}'")
                # The caller should determine the title property name and pass it in `properties`.
                # This block is problematic and should ideally be removed.
                pass
            
        payload = {
            "parent": parent,
            "properties": clean_properties
        }
        
        if children:
            # Notion API limits children to 100 per creation request
            if len(children) > 100:
                logger.warning(f"Creating page with {len(children)} blocks, which exceeds the 100 block limit. The page will be created with the first 100 blocks, and the rest should be appended separately.")
                payload["children"] = children[:100]
            else:
                payload["children"] = children

        response = requests.post(url, headers=self.headers, json=payload)

        if response.status_code != 200:
            logger.error(f"Error creating page: {response.text}")
            response.raise_for_status()

        return response.json()

    def append_block_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Append child blocks to a given block, handling chunking."""
        url = f"{self.base_url}/blocks/{block_id}/children"
        
        last_response = None
        # API has a limit of 100 children per request
        for i in range(0, len(children), 100):
            chunk = children[i:i + 100]
            payload = {"children": chunk}
            
            logger.info(f"Appending {len(chunk)} blocks to block {block_id}...")
            response = requests.patch(url, headers=self.headers, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Error appending block children: {response.text}")
                response.raise_for_status()
            
            last_response = response.json()

        return last_response or {}
        
    def get_database_schema(self, database_id: str) -> Dict[str, Any]:
        """Retrieve the schema of a database."""
        url = f"{self.base_url}/databases/{database_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            logger.error(f"Error getting database schema: {response.text}")
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
            raise ValueError("TASK_DATABASE_ID and NOTEBOOK_DATABASE_ID must be set")

        # Fetch database schemas and find title property names
        task_db_schema = self.notion.get_database_schema(self.task_database_id)
        self.task_db_title_prop = self._get_title_property_name(task_db_schema)

        notebook_db_schema = self.notion.get_database_schema(self.notebook_database_id)
        self.notebook_db_title_prop = self._get_title_property_name(notebook_db_schema)

        self._validate_database_access()

    def _get_title_property_name(self, schema: Dict[str, Any]) -> str:
        """Find the title property name from a database schema."""
        for prop_name, prop_details in schema.get("properties", {}).items():
            if prop_details.get("type") == "title":
                return prop_name
        raise ValueError("Could not find title property in database schema")

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

    def move_task_to_notebook(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Move a completed task to the Notebook DB and handle sub-tasks/archiving."""
        task_id = task["id"]
        parent_db_id = task.get("parent", {}).get("database_id", "")
        if parent_db_id.replace("-", "") != self.task_database_id.replace("-", ""):
            raise ValueError(f"Task {task_id} is not from the task database")

        is_recurring = self._is_recurring_task(task)
        blocks = self.notion.get_all_block_children(task_id)
        created_todo_tasks = self._create_tasks_from_open_todos(task, blocks)

        notebook_properties = self._map_task_to_notebook_properties(task)
        filtered_blocks = self._filter_safe_blocks(blocks)

        # Handle block chunking for page creation
        if len(filtered_blocks) > 100:
            logger.info(f"Task has {len(filtered_blocks)} blocks, which is over the 100 limit. Creating page with first 100 blocks.")
            new_page = self.notion.create_page(
                parent_id=self.notebook_database_id,
                properties=notebook_properties,
                is_database=True,
                children=filtered_blocks[:100]
            )
            logger.info(f"Successfully created notebook page {new_page['id']}. Now appending remaining blocks.")
            
            # Append the rest of the blocks in chunks
            remaining_blocks = filtered_blocks[100:]
            self.notion.append_block_children(new_page['id'], remaining_blocks)
            logger.info(f"Successfully appended remaining {len(remaining_blocks)} blocks.")

        else:
            new_page = self.notion.create_page(
                parent_id=self.notebook_database_id,
                properties=notebook_properties,
                is_database=True,
                children=filtered_blocks
            )
        
        logger.info(f"Successfully moved task {task_id} to notebook page {new_page['id']}")

        if is_recurring:
            # If handling the recurring task fails, archive it
            if not self._handle_recurring_task(task):
                self.notion.update_page(page_id=task_id, archived=True)
                logger.info(f"Archived recurring task with invalid pattern: {task_id}")
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
        for partial_task in done_tasks:
            task_id = partial_task["id"]
            try:
                logger.info(f"Processing task: {task_id}")
                # Fetch the full page object once to ensure all properties (like relations) are complete
                logger.info(f"Fetching full page object for task: {task_id}")
                full_task_obj = self.notion.get_page(task_id)

                # Pass the full task object to be moved
                result = self.move_task_to_notebook(full_task_obj)
                
                # Check recurrence using the full task object
                if self._is_recurring_task(full_task_obj):
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
        # This ensures only specified properties are mapped.
        property_map = {
            'Status', 'Priority', 'Type', 'Location', 'DoneDate', 'DoDate', 'People', 'URL', 'Time', 'Cost', 'Done'
        }

        # 1. Dynamic title property handling
        task_title_content = task['properties'].get(self.task_db_title_prop, {}).get('title', [])
        if task_title_content:
            plain_text_title = "".join(t.get("plain_text", "") for t in task_title_content)
            notebook_properties[self.notebook_db_title_prop] = {"title": [{"text": {"content": plain_text_title}}]}

        # 2. Explicitly handle the 'Project' relation property
        task_title_for_log = "".join(t.get("plain_text", "") for t in task['properties'].get(self.task_db_title_prop, {}).get('title', []))
        logger.info(f"--- Project Relation Debug for task: '{task_title_for_log}' ---")

        # Step 1: Look for the 'Project' Property
        source_project_relation_name = 'Project'
        project_property = task_properties.get(source_project_relation_name)
        logger.info(f"[Step 1] Looking for '{source_project_relation_name}'. Found: {project_property is not None}")
        if project_property:
            logger.info(f"[Step 1b] Content of property: {project_property}")

        # Step 2: Verify the Property is a Valid Relation
        is_valid_relation = project_property and project_property.get('relation') is not None
        logger.info(f"[Step 2] Is it a valid relation property? {is_valid_relation}")

        if is_valid_relation:
            # Step 3: Check if a Project is Actually Linked
            is_project_linked = bool(project_property.get('relation'))
            logger.info(f"[Step 3] Is a project linked (relation list not empty)? {is_project_linked}")
            if is_project_linked:
                # Step 4: Get ID and Add to Notebook Properties
                project_relation_id = project_property['relation'][0]['id']
                logger.info(f"[Step 4] Extracted project page ID: {project_relation_id}")
                notebook_properties['Project'] = {'relation': [{'id': project_relation_id}]}
                logger.info(f"[Step 4b] SUCCESS: Added 'Project' to notebook properties.")
        logger.info("--- End Project Relation Debug ---")

        # 3. Handle all other properties based on the explicit map
        for prop_name in property_map:
            # Skip properties already handled to avoid overwriting
            if prop_name in task_properties and prop_name not in [self.task_db_title_prop, 'Project']:
                notebook_properties[prop_name] = task_properties[prop_name]
        
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

    def _handle_recurring_task(self, task: Dict[str, Any]) -> bool:
        """Resets a recurring task's due date and status. Returns True on success."""
        pattern_info = self._find_recurring_pattern(task)
        if not pattern_info:
            logger.warning(f"No recurring pattern found for task {task['id']}. Skipping reset.")
            return False

        pattern_type, pattern_details = pattern_info
        next_date = self._calculate_next_date(pattern_type, pattern_details)
        if not next_date:
            logger.warning(f"Could not calculate next date for task {task['id']}. Skipping reset.")
            return False

        new_properties = {
            "Status": {"status": {"name": "ToDo"}},
            "DoDate": {"date": {"start": next_date.strftime('%Y-%m-%d')}}
        }
        self.notion.update_page(task["id"], properties=new_properties)
        logger.info(f"Reset recurring task {task['id']} to next date: {next_date.strftime('%Y-%m-%d')}")
        return True

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
            # Start from tomorrow to ensure it always finds the *next* occurrence
            start_date = today + timedelta(days=1)
            days_ahead = (target_weekday - start_date.weekday() + 7) % 7
            return start_date + timedelta(days=days_ahead)
        elif pattern_type == "monthly":
            day = details.get("day")
            if day is None: return None
            # If the target day is later in the current month, schedule for this month
            if today.day < day:
                try:
                    return today.replace(day=day)
                except ValueError:
                    # Handles cases where 'day' is invalid for the current month (e.g., 31 in Feb)
                    # Fallback to next month's first day or a more robust logic
                    return (today.replace(day=1) + relativedelta(months=1))
            # Otherwise, schedule for the next month
            else:
                return (today.replace(day=1) + relativedelta(months=1)).replace(day=day)
        return None

    def _filter_safe_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recursively removes unsupported blocks and problematic keys."""
        safe_blocks = []
        for block in blocks:
            block_type = block.get("type")

            # Rule 1: Skip unsupported block types entirely
            if block_type in ["unsupported", "child_database"]:
                logger.warning(f"Skipping block of type '{block_type}' to avoid validation errors.")
                continue

            # Rule 1b: Convert link_preview to bookmark
            if block_type == "link_preview":
                url = block.get("link_preview", {}).get("url")
                if url:
                    logger.info(f"Converting 'link_preview' to 'bookmark' for URL: {url}")
                    block = {"type": "bookmark", "bookmark": {"url": url}}
                    block_type = "bookmark"
                else:
                    logger.warning("Skipping 'link_preview' block with no URL.")
                    continue

            # Rule 2: For images, validate URL and only allow external URLs
            if block_type == "image":
                image_data = block.get("image", {})
                image_type = image_data.get("type")
                if image_type == "file":
                    logger.warning("Skipping 'image' block with a temporary Notion file URL.")
                    continue
                if image_type == "external":
                    url = image_data.get("external", {}).get("url")
                    if not url or not url.startswith("http"):
                        logger.warning(f"Skipping 'image' block with invalid external URL: {url}")
                        continue

            # Create a clean copy for the API, removing read-only fields
            safe_block = block.copy()
            for key in ["id", "created_by", "created_time", "last_edited_by", "last_edited_time", "parent"]:
                safe_block.pop(key, None)

            # Rule 3: Recursively filter rich_text to handle malformed mentions
            if block_type in safe_block and "rich_text" in safe_block[block_type]:
                safe_rich_text = []
                for rt_item in safe_block[block_type]["rich_text"]:
                    if rt_item.get("type") == "mention":
                        mention_data = rt_item.get("mention", {})
                        # Handle malformed 'link_preview' mentions by converting them to plain text
                        if mention_data.get("type") == "link_preview":
                            url = mention_data.get("link_preview", {}).get("url")
                            if url:
                                logger.warning(f"Converting malformed 'link_preview' mention to plain text URL: {url}")
                                safe_rich_text.append({"type": "text", "text": {"content": url}, "annotations": rt_item.get("annotations", {})})
                            continue # Skip appending the original malformed mention
                        # Check for other valid mention types
                        elif not any(key in mention_data for key in ["user", "page", "database", "date", "template_mention"]):
                            logger.warning(f"Skipping malformed mention object: {rt_item}")
                            continue
                    safe_rich_text.append(rt_item)
                safe_block[block_type]["rich_text"] = safe_rich_text

            # Rule 4: Recursively filter children of blocks that have them
            if block.get("has_children"):
                child_blocks = self.notion.get_all_block_children(block["id"])
                if child_blocks:
                    safe_block[block_type]["children"] = self._filter_safe_blocks(child_blocks)
                elif block_type in ["column_list", "synced_block"]:
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

            # Create a clean property set for the new sub-task
            new_task_props = {}

            # Set the title using the dynamic property name for the task database
            new_task_props[self.task_db_title_prop] = {"title": [{"text": {"content": todo_text}}]}

            # Set the status to 'ToDo'
            new_task_props["Status"] = {"status": {"name": "ToDo"}}

            # Copy the project relation from the parent task, if it exists
            source_project_relation_name = 'Related to ProjectsDB (1) (Tasks)'
            project_property = task.get("properties", {}).get(source_project_relation_name)
            if project_property and project_property.get('relation') and project_property['relation']:
                new_task_props['Project'] = {'relation': project_property['relation']}

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

    def get_database_schema(self, database_id: str) -> Dict[str, Any]:
        """Retrieve the schema of a database."""
        url = f"{self.notion.BASE_URL}/databases/{database_id}"
        response = self.notion._make_request("GET", url)
        return response.json()

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
