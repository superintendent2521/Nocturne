# Nocturne API Workbench

Interactive terminal UI for exploring REST, GraphQL, and WebSocket APIs using [Textual](https://textual.textualize.io/).

## Features
- Request builder for common HTTP verbs with configurable headers and body.
- GraphQL console with query and variables editors.
- WebSocket client with live activity log and connect/disconnect controls.
- Clean Textual layout with status feedback and response formatting.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # On PowerShell
pip install -r requirements.txt
```

## Run
```bash
python app.py
```

## Tips
- Headers use `Key: Value` on separate lines.
- GraphQL variables must be valid JSON.
- WebSocket messages are sent as plain text; responses stream into the activity panel.
