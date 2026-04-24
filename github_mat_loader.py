#!/usr/bin/env python3
"""
GitHub MAT File Loader - Downloads MAT files from GitHub releases
"""
import requests
import os
import tempfile
from datetime import datetime
import glob
from pathlib import Path

class GitHubMATLoader:
    def __init__(self, repo="jnschrmns/MPC-dashboard-render", cache_dir=None):
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self.download_url = f"https://github.com/{repo}/releases/download"

        # Use temp directory if no cache specified
        if cache_dir is None:
            self.cache_dir = os.path.join(tempfile.gettempdir(), "mpc_mat_cache")
        else:
            self.cache_dir = cache_dir

        # Create cache directory
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_latest_release(self):
        """Get the latest release information"""
        try:
            response = requests.get(f"{self.base_url}/releases/latest", timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Error fetching latest release: {e}")
            return None

    def download_mat_files(self, release_tag="latest", max_files=50):
        """Download MAT files from GitHub release to cache"""
        try:
            if release_tag == "latest":
                release_info = self.get_latest_release()
                if not release_info:
                    return []
                release_tag = release_info['tag_name']

            # Get release assets
            response = requests.get(f"{self.base_url}/releases/tags/{release_tag}", timeout=10)
            if response.status_code != 200:
                print(f"Release {release_tag} not found")
                return []

            release_data = response.json()
            mat_files = []

            # Download MAT files (limit to recent ones)
            assets = release_data.get('assets', [])
            mat_assets = [a for a in assets if a['name'].endswith('.mat')][-max_files:]

            for asset in mat_assets:
                file_name = asset['name']
                file_path = os.path.join(self.cache_dir, file_name)

                # Skip if already cached and recent
                if os.path.exists(file_path):
                    # Check if file is less than 1 hour old
                    file_age = datetime.now().timestamp() - os.path.getmtime(file_path)
                    if file_age < 3600:  # 1 hour cache
                        mat_files.append(file_path)
                        continue

                # Download file
                download_url = asset['browser_download_url']
                print(f"Downloading {file_name}...")

                file_response = requests.get(download_url, timeout=30)
                if file_response.status_code == 200:
                    with open(file_path, 'wb') as f:
                        f.write(file_response.content)
                    mat_files.append(file_path)
                    print(f"Downloaded {file_name}")
                else:
                    print(f"Failed to download {file_name}")

            return sorted(mat_files)

        except Exception as e:
            print(f"Error downloading MAT files: {e}")
            return []

    def get_mat_files(self, fallback_dir="results", max_files=50):
        """Get MAT files from GitHub or fallback to local directory"""
        # Try GitHub first
        github_files = self.download_mat_files(max_files=max_files)

        if github_files:
            print(f"SUCCESS: Loaded {len(github_files)} MAT files from GitHub releases")
            return github_files

        # Fallback to local directory
        print(f"WARNING: GitHub releases unavailable, using local files from {fallback_dir}")
        local_files = sorted(glob.glob(str(Path(fallback_dir) / "*.mat")))[-max_files:]
        return local_files

    def cleanup_cache(self, max_age_hours=24):
        """Remove old cached files"""
        try:
            current_time = datetime.now().timestamp()
            for file_path in glob.glob(os.path.join(self.cache_dir, "*.mat")):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_hours * 3600:
                    os.remove(file_path)
                    print(f"Removed old cached file: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"Error cleaning cache: {e}")