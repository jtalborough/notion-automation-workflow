# Notion Automation Workflow

A GitHub Actions workflow that automates recurring tasks in Notion. When tasks marked as "Done" have recurrence tags, it automatically schedules the next instance based on the tag pattern.

## Overview

This automation runs daily via GitHub Actions to:
- Check for completed tasks with recurrence tags in your Notion database
- Create new instances of recurring tasks with updated due dates
- Optionally archive non-recurring completed tasks

## Recurrence Tags

Add these tags to your Notion tasks to set up recurring schedules:
- `rec-#m`: Repeat every # months (e.g., `rec-3m` for every 3 months)
- `rec-#w`: Repeat every # weeks (e.g., `rec-2w` for every 2 weeks)
- `rec-#d`: Repeat every # days (e.g., `rec-5d` for every 5 days)
- `rec-monthly-<weekday>`: Repeat monthly on specific weekday (e.g., `rec-monthly-fri`)

## Setup

1. Fork this repository

2. Set up your Notion workspace:
   - Create a Notion integration at https://www.notion.so/my-integrations
   - Copy your integration token
   - Share your task and notebook databases with the integration
   - Copy each database ID from its URL
   - If you set `NOTION_API_VERSION` to `2025-09-03` or newer, use Notion's "Copy data source ID" action for each database, or keep the database ID and let the script resolve the first data source automatically

3. Configure GitHub repository secrets:
   - Go to Settings > Secrets and variables > Actions
   - Add three secrets:
     - `NOTION_API_TOKEN`: Your Notion integration token
     - `TASK_DATABASE_ID`: Your task database or data source ID
     - `NOTEBOOK_DATABASE_ID`: Your notebook database or data source ID
   - Optional variable:
     - `NOTION_API_VERSION`: Defaults to `2022-06-28`. Set to `2026-03-11` after confirming your IDs are data source-compatible.
     - `NOTION_REQUEST_TIMEOUT`: Defaults to `30` seconds.

4. Ensure your Notion database has these properties:
   - `Status`: Status property (for "Done" and "ToDo" states)
   - `Tag`: Multi-select property for recurrence tags
   - `DoDate`: Date property for due dates
   - `Done`: Checkbox property

The workflow will now run automatically:
- Every day at midnight (UTC)
- On every push to the main branch

## Development

If you want to run or modify the script locally:

1. Clone your fork:
```bash
git clone https://github.com/yourusername/notion-automation-workflow.git
cd notion-automation-workflow
```

2. Install Python 3.8+ and dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your credentials:
```
NOTION_API_TOKEN=your_notion_api_token
TASK_DATABASE_ID=your_task_database_or_data_source_id
NOTEBOOK_DATABASE_ID=your_notebook_database_or_data_source_id
```

4. Check connectivity without changing Notion:
```bash
python notion_script.py --check
```

5. Preview the processing flow without writes:
```bash
python notion_script.py --dry-run
```

To dry-run only one completed task:
```bash
python notion_script.py --dry-run --limit 1
```

6. Run the script:
```bash
python notion_script.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

If you encounter any issues or have questions, please open an issue in the GitHub repository. 
