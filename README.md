# Pterodactyl File Uploader

This Python script automates uploading files from a local `upload/` folder to one or more Pterodactyl servers. It preserves folder structure, skips hidden files, and ensures required directories exist on the server before uploading.

## Features

- Recursively walks `upload/` and uploads files to the server.
- Ignores hidden files (e.g., `.DS_Store`) and hidden directories.
- Creates folders on the server only once per unique path.
- Supports multiple servers filtered by egg type.
- Async uploads using `aiohttp`.

## Requirements

- Python 3.8+
- [`aiohttp`](https://pypi.org/project/aiohttp/)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

1. Set your Pterodactyl panel URL and API key at the top of the script:

```python
PANEL_URL = "https://panel.example.com"
API_KEY = "your_api_key_here"
```

2. Adjust `valid_eggs_to_sync` to select which server eggs should receive uploads.

3. Run the script:

```bash
python sync.py
```

The script will:

1. Build the list of files from `upload/`.
2. Fetch your servers from the panel filtered by eggs.
3. Create necessary directories on the server.
4. Upload all files while preserving folder structure.

## Notes

- Ensure your API key has the required permissions for server file access.
- Large uploads may take some time — the script uploads files sequentially by default.
