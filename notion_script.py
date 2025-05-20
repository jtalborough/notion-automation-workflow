import requests
import os
import re
import logging
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
                    children: Optional[List] = None) -> Dict[str, Any]:
        """Create a new page in a Notion database or as a child of another page."""
        url = f"{self.base_url}/pages"
        
        parent = {}
        if is_database:
            parent["database_id"] = parent_id
        else:
            parent["page_id"] = parent_id
            
        payload = {
            "parent": parent,
            "properties": properties
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
        
        while has_more:
            params = {}
            if start_cursor:
                params["start_cursor"] = start_cursor
                
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code != 200:
                logger.error(f"Error getting block children: {response.text}")
                response.raise_for_status()
                
            result = response.json()
            all_blocks.extend(result.get("results", []))
            
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")
            
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
                filter_dict={},
                sorts=[{"property": "created_time", "direction": "descending"}]
            )
            logger.info("Task database access validated successfully")
            
            # Try to query notebook database
            logger.info(f"Validating access to notebook database: {self.notebook_database_id}")
            self.notion.query_database(
                database_id=self.notebook_database_id,
                filter_dict={},
                sorts=[{"property": "created_time", "direction": "descending"}]
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
        
        Args:
            task_id: ID of the task to move
            
        Returns:
            Dictionary with the original and new task IDs
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
        blocks = self.notion.get_all_block_children(task_id)
        
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
            self._handle_recurring_task(task)
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
        
        return {
            "original_task_id": task_id,
            "new_notebook_page_id": new_page["id"]
        }
    
    def process_all_completed_tasks(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process all tasks marked with 'Done' status.
        Identifies recurring and non-recurring tasks, then processes them accordingly.
        
        Returns:
            Tuple of (recurring_results, non_recurring_results)
        """
        # Find all tasks with 'Done' status
        filter_dict = {
            "property": "Status",
            "status": {
                "equals": "Done"
            }
        }
        
        # Get all tasks with Done status
        done_tasks = self.notion.query_database(
            database_id=self.task_database_id,
            filter_dict=filter_dict
        )
        
        recurring_results = []
        non_recurring_results = []
        
        # Process each task based on whether it's recurring or not
        for task in done_tasks:
            task_id = task["id"]
            try:
                # Check if the task is recurring
                is_recurring = self._is_recurring_task(task)
                
                # Process the task - move to notebook and either reset or archive
                result = self.move_task_to_notebook(task_id)
                
                # Add the result to the appropriate list
                if is_recurring:
                    recurring_results.append(result)
                else:
                    non_recurring_results.append(result)
                    
            except Exception as e:
                logger.error(f"Error processing task {task_id}: {e}")
        
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
        
        # Property ID mapping from TasksDB to Notebook
        # Using the actual IDs from the database schema
        PROPERTY_MAP = {
            # Title property (Task -> Title)
            "title": "title",
            # Status property 
            "293591cd-faf9-4508-a72d-267ba96420d8": "293591cd-faf9-4508-a72d-267ba96420d8",
            # Tag property
            "Bh\\CH": "Bh\\CH",
            # Priority property
            "OxaH": "OxaH",
            # Type property
            "xR?W": "xR?W",
            # Location property
            "H]z@": "H]z@",
            # DoneDate property
            "x~tu": "x~tu",
            # DoDate property
            "tolq": "tolq",
            # Project relation property
            "a~|l": "a~|l",
            # People multi-select property
            "pCAL": "pCAL",
            # Done checkbox property
            "b5ecd428-a8f4-4cc1-b739-cde15798dc5e": "b5ecd428-a8f4-4cc1-b739-cde15798dc5e",
            # URL property
            "K`WM": "K`WM",
            # Time property
            "XD`@": "XD`@",
            # Cost property
            "e75003f5-a9dc-4d80-9388-2828842b6e73": "e75003f5-a9dc-4d80-9388-2828842b6e73",
        }
        
        # Map the title property first - it's a special case
        title_property = task_properties.get("title", {})
        if title_property.get("title"):
            notebook_properties["title"] = {
                "title": title_property.get("title", [])
            }
        
        # Map all other properties using IDs
        for prop_id, prop_data in task_properties.items():
            # Skip the title property (already handled)
            if prop_id == "title":
                continue
                
            # Check if this property ID is in our mapping
            if prop_id not in PROPERTY_MAP:
                continue
                
            notebook_prop_id = PROPERTY_MAP[prop_id]
            prop_type = prop_data.get("type")
            
            # Skip button properties and other non-transferable types
            if prop_type in ["button", "formula", "rollup"]:
                continue
            
            # Copy over the property with the same structure but using the notebook property ID
            if prop_type == "select" and prop_data.get("select"):
                notebook_properties[notebook_prop_id] = {
                    "select": prop_data.get("select")
                }
            elif prop_type == "multi_select" and prop_data.get("multi_select"):
                notebook_properties[notebook_prop_id] = {
                    "multi_select": prop_data.get("multi_select")
                }
            elif prop_type == "date" and prop_data.get("date"):
                notebook_properties[notebook_prop_id] = {
                    "date": prop_data.get("date")
                }
            elif prop_type == "rich_text" and prop_data.get("rich_text"):
                notebook_properties[notebook_prop_id] = {
                    "rich_text": prop_data.get("rich_text")
                }
            elif prop_type == "number" and prop_data.get("number") is not None:
                notebook_properties[notebook_prop_id] = {
                    "number": prop_data.get("number")
                }
            elif prop_type == "checkbox":
                notebook_properties[notebook_prop_id] = {
                    "checkbox": prop_data.get("checkbox", False)
                }
            elif prop_type == "url" and prop_data.get("url"):
                notebook_properties[notebook_prop_id] = {
                    "url": prop_data.get("url")
                }
            elif prop_type == "people" and prop_data.get("people"):
                notebook_properties[notebook_prop_id] = {
                    "people": prop_data.get("people")
                }
            elif prop_type == "relation" and prop_data.get("relation"):
                notebook_properties[notebook_prop_id] = {
                    "relation": prop_data.get("relation")
                }
            elif prop_type == "status" and prop_data.get("status"):
                notebook_properties[notebook_prop_id] = {
                    "status": prop_data.get("status")
                }
        
        # Set status to Done if it wasn't copied from the original
        status_id = "293591cd-faf9-4508-a72d-267ba96420d8"
        if status_id not in notebook_properties:
            notebook_properties[status_id] = {
                "status": {
                    "name": "Done"
                }
            }
        
        # Set DoneDate if not already set
        done_date_id = "x~tu"
        if done_date_id not in notebook_properties:
            notebook_properties[done_date_id] = {
                "date": {
                    "start": datetime.now().strftime("%Y-%m-%d")
                }
            }
        
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
    
    def _calculate_next_date(self, pattern_type: str, pattern_details: Dict[str, Any]) -> datetime:
        """
        Calculate the next occurrence date based on the recurring pattern.
        
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
