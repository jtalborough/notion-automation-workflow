import requests
import os
import re
import json
import logging
import urllib.parse
import argparse
import calendar
import sys
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
NOTION_API_VERSION = os.getenv("NOTION_API_VERSION") or "2022-06-28"
NOTION_REQUEST_TIMEOUT = float(os.getenv("NOTION_REQUEST_TIMEOUT") or "30")

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
    
    def __init__(self, api_token: Optional[str] = None, api_version: Optional[str] = None, dry_run: bool = False):
        """Initialize the Notion client with an API token."""
        self.api_token = api_token or NOTION_API_TOKEN
        if not self.api_token:
            raise ValueError("NOTION_API_TOKEN must be set in environment variables")
        self.api_version = api_version or NOTION_API_VERSION
        self.dry_run = dry_run
        self.timeout = NOTION_REQUEST_TIMEOUT
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.api_version,
        }
        self.base_url = "https://api.notion.com/v1"

    @property
    def uses_data_sources(self) -> bool:
        """Whether this Notion API version uses data sources for database rows."""
        return self.api_version >= "2025-09-03"

    @property
    def uses_in_trash(self) -> bool:
        """Whether this Notion API version expects in_trash instead of archived."""
        return self.api_version >= "2026-03-11"

    def resolve_collection_id(self, collection_id: str) -> str:
        """Return a data source ID for modern API versions, otherwise the database ID."""
        if not self.uses_data_sources:
            return collection_id

        if self._resource_exists(f"{self.base_url}/data_sources/{collection_id}"):
            return collection_id

        response = requests.get(f"{self.base_url}/databases/{collection_id}", headers=self.headers, timeout=self.timeout)
        if response.status_code != 200:
            logger.error(f"Error resolving database/data source ID {collection_id}: {response.text}")
            response.raise_for_status()

        data_sources = response.json().get("data_sources", [])
        if not data_sources:
            raise ValueError(
                f"Database {collection_id} did not expose any data sources. "
                "Use Notion's 'Copy data source ID' action and set that as the database ID secret."
            )
        resolved_id = data_sources[0]["id"]
        logger.info(f"Resolved database {collection_id} to data source {resolved_id}")
        return resolved_id

    def _resource_exists(self, url: str) -> bool:
        """Check a resource URL without logging secret-bearing headers."""
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        logger.error(f"Error checking resource: {response.text}")
        response.raise_for_status()
        return False
        
    def query_database(
        self,
        database_id: str,
        filter_dict: Optional[Dict] = None,
        sorts: Optional[List] = None,
        page_size: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query a Notion database with optional filters and sorts."""
        if self.uses_data_sources:
            url = f"{self.base_url}/data_sources/{database_id}/query"
        else:
            url = f"{self.base_url}/databases/{database_id}/query"
        
        payload = {}
        if filter_dict:
            payload["filter"] = filter_dict
        if sorts:
            payload["sorts"] = sorts
        if page_size:
            payload["page_size"] = page_size
            
        all_results = []
        has_more = True
        next_cursor = None
        pages_fetched = 0

        while has_more:
            if max_pages is not None and pages_fetched >= max_pages:
                break
            if next_cursor:
                payload["start_cursor"] = next_cursor

            response = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)

            if response.status_code != 200:
                logger.error(f"Error querying database: {response.text}")
                response.raise_for_status()

            data = response.json()
            all_results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
            pages_fetched += 1

        return all_results
        
    def get_page(self, page_id: str) -> Dict[str, Any]:
        """Get a Notion page by its ID."""
        url = f"{self.base_url}/pages/{page_id}"
        
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        
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
            payload["in_trash" if self.uses_in_trash else "archived"] = archived

        if self.dry_run:
            logger.info(f"[dry-run] Would update page {page_id}: {json.dumps(payload, default=str)}")
            return {"id": page_id, "object": "page", "dry_run": True}
            
        response = requests.patch(url, headers=self.headers, json=payload, timeout=self.timeout)
        
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
            parent = {"data_source_id": parent_id} if self.uses_data_sources else {"database_id": parent_id}
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

        if self.dry_run:
            fake_id = f"dry-run-page-{abs(hash(json.dumps(payload, sort_keys=True, default=str)))}"
            logger.info(f"[dry-run] Would create page under {parent}: {list(clean_properties.keys())}")
            return {"id": fake_id, "object": "page", "dry_run": True}

        response = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)

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
            if self.dry_run:
                logger.info(f"[dry-run] Would append {len(chunk)} blocks to block {block_id}")
                last_response = {"object": "list", "results": [], "dry_run": True}
                continue
            response = requests.patch(url, headers=self.headers, json=payload, timeout=self.timeout)
            
            if response.status_code != 200:
                logger.error(f"Error appending block children: {response.text}")
                response.raise_for_status()
            
            last_response = response.json()

        return last_response or {}
        
    def get_database_schema(self, database_id: str) -> Dict[str, Any]:
        """Retrieve the schema of a database."""
        if self.uses_data_sources:
            url = f"{self.base_url}/data_sources/{database_id}"
        else:
            url = f"{self.base_url}/databases/{database_id}"
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
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
            response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            
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

    def __init__(
        self,
        notion_client: Optional[NotionClientWrapper] = None,
        task_database_id: Optional[str] = None,
        notebook_database_id: Optional[str] = None,
    ):
        """Initialize the task service with a Notion client."""
        self.notion = notion_client or NotionClientWrapper()
        self.task_database_id = task_database_id or TASK_DATABASE_ID
        self.notebook_database_id = notebook_database_id or NOTEBOOK_DATABASE_ID
        if not self.task_database_id or not self.notebook_database_id:
            raise ValueError("TASK_DATABASE_ID and NOTEBOOK_DATABASE_ID must be set")

        self.task_database_id = self.notion.resolve_collection_id(self.task_database_id)
        self.notebook_database_id = self.notion.resolve_collection_id(self.notebook_database_id)
        self.errors: List[Tuple[str, Exception]] = []

        # Fetch database schemas and find title property names
        task_db_schema = self.notion.get_database_schema(self.task_database_id)
        self.task_db_title_prop = self._get_title_property_name(task_db_schema)

        notebook_db_schema = self.notion.get_database_schema(self.notebook_database_id)
        self.notebook_db_title_prop = self._get_title_property_name(notebook_db_schema)
        self.notebook_property_names = set(notebook_db_schema.get("properties", {}).keys())

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
            self.notion.query_database(
                self.task_database_id,
                page_size=1,
                max_pages=1,
            )
            logger.info("Successfully connected to the Task database.")
        except Exception as e:
            logger.error(f"Failed to connect to the Task database: {e}")
            raise
        try:
            self.notion.query_database(
                self.notebook_database_id,
                page_size=1,
                max_pages=1,
            )
            logger.info("Successfully connected to the Notebook database.")
        except Exception as e:
            logger.error(f"Failed to connect to the Notebook database: {e}")
            raise

    def move_task_to_notebook(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Move a completed task to the Notebook DB and handle sub-tasks/archiving."""
        task_id = task["id"]
        parent = task.get("parent", {})
        parent_db_id = parent.get("data_source_id") or parent.get("database_id", "")
        if parent_db_id.replace("-", "") != self.task_database_id.replace("-", ""):
            raise ValueError(f"Task {task_id} is not from the task database")

        is_recurring = self._is_recurring_task(task)
        blocks = self.notion.get_all_block_children(task_id)
        created_todo_tasks = []

        notebook_properties = self._map_task_to_notebook_properties(task)
        filtered_blocks = self._filter_safe_blocks(blocks)

        # Prepare log blocks to be added to the new page
        log_blocks = []
        done_date = task.get("properties", {}).get("DoneDate", {}).get("date") or {}
        done_date_str = done_date.get("start")
        if done_date_str:
            # Format the date to be more readable if it's a full datetime string
            try:
                done_date = datetime.fromisoformat(done_date_str)
                formatted_done_date = done_date.strftime('%Y-%m-%d @ %H:%M')
                log_blocks.append(self._create_log_block(f"Completed on: {formatted_done_date}"))
            except ValueError:
                log_blocks.append(self._create_log_block(f"Completed on: {done_date_str}"))

        next_date = None
        if is_recurring:
            pattern_info = self._find_recurring_pattern(task)
            if pattern_info:
                pattern_type, pattern_details = pattern_info
                next_date = self._calculate_next_date(pattern_type, pattern_details)
            if next_date:
                log_blocks.append(self._create_log_block(f"Reset to: {next_date.strftime('%Y-%m-%d')}"))

        if log_blocks:
            log_blocks.append(self._create_divider_block())

        final_blocks = log_blocks + filtered_blocks

        # Handle block chunking for page creation with final blocks
        if len(final_blocks) > 100:
            logger.info(f"Task has {len(final_blocks)} total blocks, which is over the 100 limit. Creating page with first 100 blocks.")
            new_page = self.notion.create_page(
                parent_id=self.notebook_database_id,
                properties=notebook_properties,
                is_database=True,
                children=final_blocks[:100]
            )
            logger.info(f"Successfully created notebook page {new_page['id']}. Now appending remaining blocks.")
            
            remaining_blocks = final_blocks[100:]
            self.notion.append_block_children(new_page['id'], remaining_blocks)
            logger.info(f"Successfully appended remaining {len(remaining_blocks)} blocks.")
        else:
            new_page = self.notion.create_page(
                parent_id=self.notebook_database_id,
                properties=notebook_properties,
                is_database=True,
                children=final_blocks
            )

        created_todo_tasks = self._create_tasks_from_open_todos(task, blocks)

        if is_recurring:
            if next_date:
                new_properties = {
                    "Status": {"status": {"name": "ToDo"}},
                    "DoDate": {"date": {"start": next_date.strftime('%Y-%m-%d')}}
                }
                self.notion.update_page(task["id"], properties=new_properties)
                logger.info(f"Reset recurring task {task['id']} to next date: {next_date.strftime('%Y-%m-%d')}")
                if log_blocks:
                    logger.info(f"Appending completion log to original task {task_id}")
                    task_log_blocks = log_blocks + [self._create_divider_block()]
                    self.notion.append_block_children(task_id, task_log_blocks)
            else:
                self.notion.update_page(page_id=task_id, archived=True)
                logger.info(f"Archived recurring task with invalid pattern: {task_id}")
        else:
            self.notion.update_page(page_id=task_id, archived=True)
            logger.info(f"Archived non-recurring task {task_id}")
        
        logger.info(f"Successfully moved task {task_id} to notebook page {new_page['id']}")

        return {
            "original_task_id": task_id,
            "new_notebook_page_id": new_page["id"],
            "created_todo_tasks": created_todo_tasks
        }

    def process_all_completed_tasks(self, limit: Optional[int] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Finds and processes all 'Done' tasks."""
        filter_dict = {"property": "Status", "status": {"equals": "Done"}}
        logger.info("Querying for tasks with status 'Done'")
        done_tasks = self.notion.query_database(self.task_database_id, filter_dict)
        if limit is not None:
            done_tasks = done_tasks[:limit]
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
                self.errors.append((task_id, e))

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
        source_project_relation_name = 'Project'
        project_property = task_properties.get(source_project_relation_name)
        is_valid_relation = project_property and project_property.get('relation') is not None

        if is_valid_relation:
            if project_property.get('relation'):
                project_relation_id = project_property['relation'][0]['id']
                notebook_properties['Project'] = {'relation': [{'id': project_relation_id}]}
                logger.info("Mapped Project relation to notebook page.")

        # 3. Handle all other properties based on the explicit map
        for prop_name in property_map:
            # Skip properties already handled to avoid overwriting
            if (
                prop_name in task_properties
                and prop_name in self.notebook_property_names
                and prop_name not in [self.task_db_title_prop, 'Project']
            ):
                if not self._has_writable_property_value(task_properties[prop_name]):
                    continue
                notebook_properties[prop_name] = task_properties[prop_name]
        
        logger.info(f"Mapped properties for notebook page: {list(notebook_properties.keys())}")
        return notebook_properties

    def _has_writable_property_value(self, property_value: Dict[str, Any]) -> bool:
        """Skip empty Notion property values that cannot be written into a new page."""
        prop_type = property_value.get("type")
        if not prop_type:
            return False
        return property_value.get(prop_type) is not None

    def _is_recurring_task(self, task: Dict[str, Any]) -> bool:
        """Checks if a task is recurring."""
        properties = task.get("properties", {})
        if properties.get("Recurring", {}).get("formula", {}).get("boolean"): 
            return True
        tags = properties.get("Recurrence", {}).get("multi_select", [])
        return any(RECURRING_RELATIVE_PATTERN.match(t["name"]) or RECURRING_WEEKLY_PATTERN.match(t["name"]) or RECURRING_MONTHLY_PATTERN.match(t["name"]) for t in tags)

    def _find_recurring_pattern(self, task: Dict[str, Any]) -> Optional[Tuple[str, dict]]:
        """Finds the recurring pattern from a task's tags."""
        tags = task.get("properties", {}).get("Recurrence", {}).get("multi_select", [])
        for tag in tags:
            name = tag.get("name", "")
            if m := RECURRING_RELATIVE_PATTERN.match(name):
                return "relative", {"count": int(m.group(1)), "unit": m.group(2)}
            if m := RECURRING_WEEKLY_PATTERN.match(name):
                return "weekly", {"weekday": WEEKDAY_MAP.get(m.group(1).lower())}
            if m := RECURRING_MONTHLY_PATTERN.match(name):
                return "monthly", {"day": int(m.group(1))}
        return None

    def _handle_recurring_task(self, task: Dict[str, Any]) -> Optional[datetime]:
        """Resets a recurring task's due date and status. Returns the next date on success."""
        pattern_info = self._find_recurring_pattern(task)
        if not pattern_info:
            logger.warning(f"No recurring pattern found for task {task['id']}. Skipping reset.")
            return None

        pattern_type, pattern_details = pattern_info
        next_date = self._calculate_next_date(pattern_type, pattern_details)
        if not next_date:
            logger.warning(f"Could not calculate next date for task {task['id']}. Skipping reset.")
            return None

        new_properties = {
            "Status": {"status": {"name": "ToDo"}},
            "DoDate": {"date": {"start": next_date.strftime('%Y-%m-%d')}}
        }
        self.notion.update_page(task["id"], properties=new_properties)
        logger.info(f"Reset recurring task {task['id']} to next date: {next_date.strftime('%Y-%m-%d')}")
        return next_date

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
                return self._date_for_monthly_day(today, day)
            # Otherwise, schedule for the next month
            else:
                return self._date_for_monthly_day(today.replace(day=1) + relativedelta(months=1), day)
        return None

    def _date_for_monthly_day(self, base_date: datetime, requested_day: int) -> datetime:
        """Return the requested day in base_date's month, clamped to month end."""
        last_day = calendar.monthrange(base_date.year, base_date.month)[1]
        return base_date.replace(day=min(requested_day, last_day))

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
            for key in [
                "id", "object", "created_by", "created_time", "last_edited_by",
                "last_edited_time", "parent", "archived", "in_trash", "has_children"
            ]:
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

            safe_blocks.append(self._strip_null_values(safe_block))
        return safe_blocks

    def _strip_null_values(self, value: Any) -> Any:
        """Remove null fields from copied Notion API responses before create requests."""
        if isinstance(value, dict):
            return {k: self._strip_null_values(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [self._strip_null_values(item) for item in value]
        return value

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
            logger.info(f"Created new task {new_task['id']} from open to-do block.")

        return created_tasks

    def _create_log_block(self, text: str) -> Dict[str, Any]:
        """Creates a paragraph block for logging information."""
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": text
                    }
                }]
            }
        }

    def _create_divider_block(self) -> Dict[str, Any]:
        """Creates a divider block."""
        return {
            "object": "block",
            "type": "divider",
            "divider": {}
        }

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process completed recurring tasks in Notion.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate credentials, schema access, and the completed-task query without changing Notion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the processing flow but log intended Notion writes instead of creating, updating, or appending.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process at most this many completed tasks. Useful with --dry-run for validation.",
    )
    return parser.parse_args()


def main():
    """Main script execution."""
    args = parse_args()
    try:
        if not all([NOTION_API_TOKEN, TASK_DATABASE_ID, NOTEBOOK_DATABASE_ID]):
            print("Error: Missing one or more required environment variables.")
            sys.exit(1)

        notion_client = NotionClientWrapper(dry_run=args.dry_run)
        task_service = TaskService(notion_client=notion_client)

        if args.check:
            print("Connection check passed.")
            print(f"Notion API version: {notion_client.api_version}")
            print(f"Task collection ID: {task_service.task_database_id}")
            print(f"Notebook collection ID: {task_service.notebook_database_id}")
            done_tasks = task_service.notion.query_database(
                task_service.task_database_id,
                {"property": "Status", "status": {"equals": "Done"}},
                page_size=1,
                max_pages=1,
            )
            print(f"Completed-task query passed; first page returned {len(done_tasks)} item(s).")
            return

        print("Processing all completed tasks...")
        if args.dry_run:
            print("Dry run enabled: Notion writes will be logged but not sent.")
        recurring, non_recurring = task_service.process_all_completed_tasks(limit=args.limit)

        print(f"\nProcessed {len(recurring)} recurring tasks.")
        print(f"Processed {len(non_recurring)} non-recurring tasks.")
        total = len(recurring) + len(non_recurring)
        print(f"Total tasks processed: {total}")
        if task_service.errors:
            failed_ids = ", ".join(task_id for task_id, _ in task_service.errors)
            raise RuntimeError(f"Failed to process {len(task_service.errors)} task(s): {failed_ids}")

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
        sys.exit(1)

if __name__ == "__main__":
    main()
