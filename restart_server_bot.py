#!/usr/bin/env python3
"""Restart bot on server"""
import paramiko
import time

# Server details
hostname = "155.212.162.47"
username = "root"
password = "Booking2025"
port = 22

try:
    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to {hostname}...")
    ssh.connect(hostname, port=port, username=username, password=password)

    # Stop bot
    print("Stopping bot...")
    stdin, stdout, stderr = ssh.exec_command("systemctl stop booking-bot")
    stdout.channel.recv_exit_status()  # Wait for command to complete
    print("Bot stopped")

    # Wait a bit
    time.sleep(2)

    # Start bot
    print("Starting bot...")
    stdin, stdout, stderr = ssh.exec_command("systemctl start booking-bot")
    stdout.channel.recv_exit_status()
    print("Bot started")

    # Wait a bit
    time.sleep(2)

    # Check status
    print("\nChecking bot status...")
    stdin, stdout, stderr = ssh.exec_command("systemctl status booking-bot")
    status_output = stdout.read().decode()
    print(status_output)

    # Check logs
    print("\nRecent logs:")
    stdin, stdout, stderr = ssh.exec_command("journalctl -u booking-bot -n 20 --no-pager")
    logs = stdout.read().decode()
    print(logs)

    ssh.close()

    print("\nBot restarted successfully!")

except Exception as e:
    print(f"Error: {e}")
    exit(1)
