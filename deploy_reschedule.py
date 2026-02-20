#!/usr/bin/env python3
"""Deploy reschedule feature files to server"""
import paramiko

hostname = "155.212.162.47"
username = "root"
password = "***REMOVED***"

import os
BASE = r"C:\Users\User\booking_bot"

files_to_upload = [
    (os.path.join(BASE, "webapp", "server.py"), "/opt/booking_bot/webapp/server.py"),
    (os.path.join(BASE, "webapp", "static", "js", "booking.js"), "/opt/booking_bot/webapp/static/js/booking.js"),
    (os.path.join(BASE, "webapp", "templates", "booking.html"), "/opt/booking_bot/webapp/templates/booking.html"),
    (os.path.join(BASE, "webapp", "static", "css", "booking.css"), "/opt/booking_bot/webapp/static/css/booking.css"),
]

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {hostname}...")
    ssh.connect(hostname, port=22, username=username, password=password, timeout=30)

    sftp = ssh.open_sftp()
    for local_path, remote_path in files_to_upload:
        print(f"Uploading {local_path} -> {remote_path}")
        sftp.put(local_path, remote_path)
        print(f"  [OK]")

    sftp.close()

    print("\nRestarting booking-bot service...")
    stdin, stdout, stderr = ssh.exec_command("systemctl restart booking-bot")
    exit_code = stdout.channel.recv_exit_status()
    print(f"Restart exit code: {exit_code}")

    import time
    time.sleep(3)

    print("\nChecking status...")
    stdin, stdout, stderr = ssh.exec_command("systemctl status booking-bot --no-pager -l")
    print(stdout.read().decode())

    ssh.close()
    print("Deploy completed!")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
