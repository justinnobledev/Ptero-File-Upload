from asyncio import run, TimeoutError
import ctypes
from dataclasses import dataclass
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from aiohttp import ClientSession, ClientError, ContentTypeError, FormData

PANEL_URL = "https://panel.insanitygaming.net"
API_KEY = ""

DEBUG = False

valid_images = ["docker.io/sples1/k4ryuu-cs2:latest"]

exclude_servers = ["1v1"]

@dataclass
class Server:
    UUID: str
    Identifier: str
    Name: str

async def fetch(session: ClientSession, url: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Fetch JSON data from a URL safely using an existing aiohttp session."""
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status == 200:
                # Try to parse JSON
                try:
                    return await response.json()
                except ContentTypeError:
                    print(f"⚠️ Non-JSON response from {url}")
                    return None
            else:
                print(f"⚠️ Request failed {response.status} for {url}")
                return None
    except TimeoutError:
        print(f"⏱️ Timeout fetching {url}")
        return None
    except ClientError as e:
        print(f"❌ Network error while fetching {url}: {e}")
        return None

async def folder_exists(session: ClientSession, server_id: str, path: str, directory: str) -> bool:
    """Check if a folder exists on the server."""
    url = f"{PANEL_URL}/api/client/servers/{server_id}/files/list"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "Application/vnd.pterodactyl.v1+json",
    }
    params = {"directory": path or "/"}
    try:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                # data['data'] is a list of files/folders in that directory
                # Check if a folder with the last part of the path exists
                for item in data["data"]:
                    if item['attributes']["name"] == directory and not item['attributes']["is_file"]:
                        return True
                return False
            else:
                print(f"⚠️ Failed to list {path}: {resp.status}")
                return False
    except Exception as e:
        print(f"❌ Error checking folder {path}: {e}")
        return False

async def ensure_folders(session: ClientSession, id: str, path: str) -> bool:
    """Ensure all subfolders in 'path' exist, creating them if needed."""
    parts = path.strip("/").split("/")
    current_root = "/"
    for part in parts:
        if not part:
            continue
        if not await create_folder(session, id, part, current_root):
            return False
        current_root = os.path.join(current_root, part).replace("\\", "/")
    return True

async def create_folder(session: ClientSession, id: str, name: str, root: str) -> bool:
    url = f"{PANEL_URL}/api/client/servers/{id}/files/create-folder"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        'Accept': 'Application/vnd.pterodactyl.v1+json',
        "Content-Type": "application/json",
    }
    
    if await folder_exists(session, id, root, name):
        if DEBUG:
            print(f"📂 Folder {os.path.join(root, name)} already exists")
        return True
    
    payload = {"name": name, "root": root or "/"}
    async with session.post(url, headers=headers, json=payload) as resp:
        if resp.status == 204:
            print(f"📁 Created folder {os.path.join(root, name)}")
        elif resp.status == 400:
            pass  # already exists
        else:
            print(f"⚠️ Failed to create folder {name} in {root}: {resp.status} {await resp.text()}")
            return False
    return True

async def upload_file(session: ClientSession, server_id: str, local_path: str, remote_path: str) -> bool:
    directory = "/" + os.path.dirname(remote_path).lstrip("/")  # ensure proper leading slash
    
    # if directory and directory != "/":
    #     await ensure_folders(session, server_id, directory)

    # Step 1: Get signed upload URL
    url = f"{PANEL_URL}/api/client/servers/{server_id}/files/upload"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/vnd.pterodactyl.v1+json",
    }
    params = {"directory": directory}
    resp = await session.get(url, headers=headers, params=params)
    if resp.status != 200:
        print(f"❌ Failed to get upload URL for {remote_path}: {resp.status} {await resp.text()}")
        return False
    data = await resp.json()
    signed_url = data["attributes"]["url"]

    # Step 2: Upload file to signed URL using FormData
    form = FormData()
    with open(local_path, "rb") as f:
        form.add_field("files", f, filename=os.path.basename(local_path))
        # form.add_field("directory", directory)  # optional, can be omitted if signed URL already scoped

        async with session.post(signed_url, data=form, params=params) as upload_resp:
            if upload_resp.status in (200, 204):
                print(f"✅ Uploaded {local_path} -> {remote_path}")
            else:
                print(f"❌ Upload failed for {local_path} -> {remote_path}: {upload_resp.status} {await upload_resp.text()}")
                
    return True
  
async def build_server_list() -> List[Server]:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    servers:List[Server] = []
    async with ClientSession() as session:
        data = await fetch(session, f"{PANEL_URL}/api/client", headers)
        if data:
            for server in data["data"]:
                attrs = server["attributes"]
                docker_image = attrs["docker_image"]
                name = attrs['name']
                for excluded in exclude_servers:
                    if excluded in name:
                        continue
                
                if DEBUG and not ('Dev' in name):
                    continue
                
                if docker_image not in valid_images:
                    continue
                
                s = Server(
                    UUID=attrs["uuid"],
                    Identifier=attrs["identifier"],
                    Name=attrs["name"],
                )
                servers.append(s)
    return servers

def is_hidden(filepath: str) -> bool:
    """
    Returns True if the file is hidden based on OS rules.
    - Unix: hidden if name starts with '.'
    - Windows: hidden if FILE_ATTRIBUTE_HIDDEN flag is set
    """
    if sys.platform.startswith("win"):
        FILE_ATTRIBUTE_HIDDEN = 0x02
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(filepath))
        if attrs == -1:
            return False
        return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
    else:
        return os.path.basename(filepath).startswith(".")

def build_files() -> List[Tuple[str, str]]:
    """
    Returns a list of tuples: (local_path, remote_path)
    Remote paths are relative to the server base folder,
    preserving the folder structure under 'upload/'.
    """
    files_to_upload: List[Tuple[str, str]] = []

    for root, dirs, files in os.walk("upload"):
        dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
        for file in files:
            
            local_path = os.path.join(root, file)
            if is_hidden(local_path):
                continue
            # Relative path on server (strip 'upload/' prefix)
            rel_path = os.path.relpath(local_path, "upload")
            remote_path = rel_path.replace("\\", "/")  # normalize for Linux
            files_to_upload.append((local_path, remote_path))

    return files_to_upload

async def main():
    files = build_files()
    servers = await build_server_list()
    
    async with ClientSession() as session:
        for server in servers:
            print(f'📂 Ensuring folder structure for {server.Name}...')

            # --- Collect unique folders ---
            # Collect only the final directory of each file (deduplicated)
            dirs_to_make = set()
            for _, remote_path in files:
                directory = "/" + os.path.dirname(remote_path).lstrip("/")
                if directory and directory != "/":
                    parts = directory.strip("/").split("/")
                    for i in range(1, len(parts) + 1):
                        dirs_to_make.add("/" + "/".join(parts[:i]))

            # Sort so parents come before children
            for path in sorted(dirs_to_make, key=lambda x: x.count("/")):
                name = os.path.basename(path)
                root = os.path.dirname(path) or "/"
                if not await create_folder(session, server.Identifier, name, root):
                    raise Exception(f"Failed to create folder {root}/{name} on {server.Name}")
            
            print(f'Starting file upload for {server.Name}')
            for (local, rel) in files:
                await upload_file(session, server.Identifier, local, rel)        
    
# Run the event loop
if __name__ == "__main__":
    run(main())