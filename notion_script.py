import requests
import os
from dotenv import load_dotenv
import re
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Define the Notion API endpoint for your tasksDB
NOTION_API_URL = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

# Define headers with your integration token
headers = {
    "Authorization": f"Bearer {NOTION_API_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Function to calculate the new DoDate based on the tag

# Define the filter conditions to only retrieve tasks where 'Status' is 'Done'
filter_params =     {
    "filter": {
        "and": 
        [
            {
            "property": "Status",
            "status": {
                "equals": "Done"
                 }
            }, 
            {
            "property": "Recurring",
            "formula": {
                "checkbox": {
                    "equals": True
                     }
                }
            }
        ]
    }
    }

archive=False
def calculate_new_dodate(tag):
    new_dodate = None
    pattern = r"rec[-_](\w+)([-_](\d+|[a-zA-Z]+))?"
    match = re.match(pattern, tag, re.IGNORECASE)
    
    if match:
        frequency, _, day_or_date = match.groups()
        today = datetime.today()
        
        # Handle cases for months
        if frequency.endswith("m"):
            months = int(frequency[:-1])
            new_dodate = today + relativedelta(months=months)
        
        # Handle cases for weeks
        elif frequency.endswith("w"):
            weeks = int(frequency[:-1])
            new_dodate = today + timedelta(weeks=weeks)
        
        # Handle cases for days
        elif frequency.endswith("d"):
            days = int(frequency[:-1])
            new_dodate = today + timedelta(days=days)
        
        # Handle specific days of the month or quarter
        # Handle specific days of the month
        if day_or_date:
            if frequency == "monthly":
                new_dodate = today.replace(day=int(day_or_date))
                if today.day > int(day_or_date):
                    new_dodate += relativedelta(months=1)

        
        # Handle specific weekdays (e.g., 'fri' for Friday)
        weekday_str_to_int = {
            'm': 0, 'mon': 0, 'monday': 0,
            't': 1, 'tue': 1, 'tuesday': 1,
            'w': 2, 'wed': 2, 'wednesday': 2,
            'th': 3, 'thu': 3, 'thursday': 3,
            'f': 4, 'fri': 4, 'friday': 4,
            'sa': 5, 'sat': 5, 'saturday': 5,
            'su': 6, 'sun': 6, 'sunday': 6
        }
        target_weekday = weekday_str_to_int.get(day_or_date.lower() if day_or_date else '', None)
        if target_weekday is not None:
            days_until_target = (target_weekday - today.weekday() + 7) % 7
            new_dodate = today + timedelta(days=days_until_target)
        
        return new_dodate.strftime("%Y-%m-%d") if new_dodate else None
    
    return None
# Make a POST request to retrieve tasks based on the filter
print("Fetching tasks from Notion API...")
response = requests.post(NOTION_API_URL, headers=headers, json=filter_params)

# Debug statement to print the API response
print("API Response for fetching tasks:")
print(response.json())
print("\n\n")
# Check if the request was successful
if response.status_code == 200:
    tasks = response.json()["results"]
    
    # Loop through the retrieved tasks and implement your automation logic
    for task in tasks:
        # Fetch the "Tag" of each task
        tag_values = task.get("properties", {}).get("Tag", {}).get("multi_select", [])
        
        # Filter tasks based on the custom tag schema "Recurring_type_#period"
        recurring_tasks = [tag["name"] for tag in tag_values if "rec" in tag["name"].lower()]
        
        if recurring_tasks:
            # Your logic to handle recurring tasks goes here
            # For example, calculate a new "DoDate"
            for recurring_tag in recurring_tasks:
                new_dodate = calculate_new_dodate(recurring_tag)
                if new_dodate:
                    # Implement logic to update the task with the new "DoDate" and change "Status" to "ToDo"
                    task_id = task["id"]
                    new_status = "ToDo"
                    update_data = {
                        "properties": {
                            "DoDate": {
                                "date": {
                                    "start": new_dodate
                                }
                            },
                            "Status": {
                                "status": {
                                    "name": new_status
                                }
                            },
                            "Done": {
                                "checkbox": False
                            }
                        }
                    }
                    update_url = f"https://api.notion.com/v1/pages/{task_id}"
                    update_response = requests.patch(update_url, headers=headers, json=update_data)
                    
                    # Debug statement to print the API response
                    print("API Response for updating task:")
                    print(update_response.json())
                    print("/n/n")
                    
                    if update_response.status_code == 200:
                        print(f"Task {task_id} updated successfully.")
                        print("\n\n")
                    else:
                        print(f"Error updating task {task_id}.")
                        print(f"Response content: {update_response.text}")
                        print("\n\n")
        else:
            if(archive):
                # Your logic to archive non-recurring tasks goes here
                task_id = task["id"]
                archive_data = {
                    "archived": True
                }
                archive_url = f"https://api.notion.com/v1/pages/{task_id}"
                archive_response = requests.patch(archive_url, headers=headers, json=archive_data)
        
        
                # Debug statement to print the API response
                print("API Response for archiving task:")
                print(archive_response.json())
                print("\n\n")
                
                if archive_response.status_code == 200:
                    print(f"Task {task_id} archived successfully.")
                    print("\n\n")
                else:
                    print(f"Error archiving task {task_id}.")
                    print(f"Response content: {archive_response.text}")
                    print("\n\n")
else:
    print("Error: Unable to retrieve tasks from Notion API")
    print(f"Response content: {response.text}")
    print("\n\n")
