#!/usr/bin/env python3
"""Check bot logs on server"""
import paramiko

# Server details
hostname = "155.212.162.47"
username = "root"
password = "***REMOVED***"
port = 22

try:
    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to {hostname}...")
    ssh.connect(hostname, port=port, username=username, password=password)

    # Check logs
    print("Recent logs:")
    stdin, stdout, stderr = ssh.exec_command("journalctl -u booking-bot -n 30 --no-pager")
    logs = stdout.read().decode('utf-8', errors='replace')
    print(logs)

    ssh.close()

except Exception as e:
    print(f"Error: {e}")
    exit(1)
