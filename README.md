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
   - Share your database with the integration
   - Copy your database ID from its URL

3. Configure GitHub repository secrets:
   - Go to Settings > Secrets and variables > Actions
   - Add two secrets:
     - `NOTION_API_TOKEN`: Your Notion integration token
     - `NOTION_DATABASE_ID`: Your Notion database ID

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
NOTION_DATABASE_ID=your_notion_database_id
```

4. Run the script:
```bash
python notion_script.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

If you encounter any issues or have questions, please open an issue in the GitHub repository. 
