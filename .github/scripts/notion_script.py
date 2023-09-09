# .github/scripts/notion_script.py

import requests
import json
import os
from datetime import datetime, timedelta

NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

headers = {
    "Authorization": f"Bearer {NOTION_API_TOKEN}",
    "Notion-Version": "2021-08-16",
    "Content-Type": "application/json"
}

def query_notion_database():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    data = {
        "filter": {
            "property": "Status",
            "text": {
                "equals": "Done"
            }
        }
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def reschedule_task(task_id, new_date):
    url = f"https://api.notion.com/v1/pages/{task_id}"
    data = {
        "properties": {
            "Due Date": {
                "type": "date",
                "date": {
                    "start": new_date
                }
            }
        }
    }
    requests.patch(url, headers=headers, json=data)

if __name__ == "__main__":
    tasks = query_notion_database().get("results", [])
    for task in tasks:
        task_id = task["id"]
        tags = task["properties"].get("Tags", {}).get("multi_select", [])
        due_date = task["properties"].get("Due Date", {}).get("date", {}).get("start", "")
        
        if due_date:
            due_date = datetime.strptime(due_date, "%Y-%m-%d")
        
        for tag in tags:
            if tag["name"] == "Weekly":
                new_date = (due_date + timedelta(days=7)).strftime("%Y-%m-%d")
                reschedule_task(task_id, new_date)
            elif tag["name"] == "Monthly":
                new_date = (due_date + timedelta(days=30)).strftime("%Y-%m-%d")
                reschedule_task(task_id, new_date)
