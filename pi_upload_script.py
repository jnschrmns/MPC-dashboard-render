#!/usr/bin/env python3
"""
Pi Upload Script - Automatically uploads new MAT files to GitHub releases
Run this script on the Pi every 5-10 minutes via cron
"""

import os
import glob
import requests
import json
from datetime import datetime
from pathlib import Path
import tempfile
import zipfile
import time

class GitHubReleaseUploader:
    def __init__(self, repo="jnschrmns/MPC-dashboard-render", token=None):
        self.repo = repo
        self.token = token  # GitHub personal access token
        self.base_url = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {token}" if token else None
        }

    def create_daily_release(self):
        """Create or update today's release"""
        today = datetime.now().strftime("%Y%m%d")
        tag_name = f"mpc-data-{today}"
        release_name = f"MPC Data {today}"

        # Check if release already exists
        try:
            response = requests.get(f"{self.base_url}/releases/tags/{tag_name}",
                                  headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()  # Release exists
        except Exception:
            pass

        # Create new release
        release_data = {
            "tag_name": tag_name,
            "name": release_name,
            "body": f"Automated MPC data upload for {today}\\nContains latest MAT files from Pi",
            "draft": False,
            "prerelease": False
        }

        try:
            response = requests.post(f"{self.base_url}/releases",
                                   headers=self.headers,
                                   data=json.dumps(release_data),
                                   timeout=15)
            if response.status_code == 201:
                print(f"Created new release: {tag_name}")
                return response.json()
            else:
                print(f"Failed to create release: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error creating release: {e}")
            return None

    def upload_mat_files(self, mat_dir="/homeassistant/mpc/python_mpc/pi_mpc_deployment/mpc_enhanced/results",
                        max_files=100):
        """Upload recent MAT files to today's release"""
        if not self.token:
            print("ERROR: No GitHub token provided")
            return False

        # Get today's release
        release = self.create_daily_release()
        if not release:
            print("ERROR: Could not create/access release")
            return False

        # Find recent MAT files
        mat_pattern = os.path.join(mat_dir, "mpc_result_*.mat")
        mat_files = sorted(glob.glob(mat_pattern))[-max_files:]

        if not mat_files:
            print(f"No MAT files found in {mat_dir}")
            return False

        print(f"Found {len(mat_files)} MAT files to upload")

        # Get existing assets to avoid duplicates
        existing_assets = {asset['name'] for asset in release.get('assets', [])}

        uploaded_count = 0
        for mat_file in mat_files:
            file_name = os.path.basename(mat_file)

            # Skip if already uploaded
            if file_name in existing_assets:
                continue

            # Upload file
            if self.upload_asset(release, mat_file):
                uploaded_count += 1
                print(f"Uploaded: {file_name}")
            else:
                print(f"Failed to upload: {file_name}")

            # Rate limiting - GitHub API allows 5000 requests/hour
            time.sleep(0.1)

        print(f"Upload complete: {uploaded_count} new files uploaded")
        return True

    def upload_asset(self, release, file_path):
        """Upload a single file as release asset"""
        try:
            file_name = os.path.basename(file_path)
            upload_url = release['upload_url'].replace('{?name,label}', f'?name={file_name}')

            with open(file_path, 'rb') as f:
                file_content = f.read()

            headers = self.headers.copy()
            headers['Content-Type'] = 'application/octet-stream'

            response = requests.post(upload_url,
                                   headers=headers,
                                   data=file_content,
                                   timeout=30)

            return response.status_code == 201

        except Exception as e:
            print(f"Error uploading {file_path}: {e}")
            return False

def main():
    """Main upload function for cron execution"""
    # GitHub token should be set as environment variable for security
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set")
        print("Please create a GitHub Personal Access Token with 'repo' permissions")
        return False

    # Custom MAT directory if provided
    mat_dir = os.environ.get('MAT_DIR',
                           '/homeassistant/mpc/python_mpc/pi_mpc_deployment/mpc_enhanced/results')

    print(f"Starting upload from {mat_dir}")

    uploader = GitHubReleaseUploader(token=token)
    success = uploader.upload_mat_files(mat_dir=mat_dir, max_files=50)

    if success:
        print("Upload completed successfully")
    else:
        print("Upload failed")

    return success

if __name__ == "__main__":
    main()