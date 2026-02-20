#!/usr/bin/env python3
"""Upload files to server via SFTP"""
import paramiko
import os

# Server details
hostname = "155.212.162.47"
username = "root"
password = "Booking2025"
port = 22

# Files to upload
files_to_upload = [
    ("bot/handlers/client.py", "/opt/booking_bot/bot/handlers/client.py"),
    ("bot/keyboards/client_kb.py", "/opt/booking_bot/bot/keyboards/client_kb.py"),
]

try:
    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to {hostname}...")
    ssh.connect(hostname, port=port, username=username, password=password)

    # Create SFTP client
    sftp = ssh.open_sftp()

    # Upload files
    for local_path, remote_path in files_to_upload:
        print(f"Uploading {local_path} to {remote_path}...")
        sftp.put(local_path, remote_path)
        print(f"[OK] {local_path} uploaded successfully")

    sftp.close()
    ssh.close()

    print("\nAll files uploaded successfully!")

except Exception as e:
    print(f"Error: {e}")
    exit(1)
