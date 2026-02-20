#!/usr/bin/env python3
import paramiko
import sys
sys.stdout.reconfigure(encoding='utf-8')

HOST = "155.212.162.47"
USER = "root"
PASSWORD = "***REMOVED***"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)

print("Bot process:")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'python.*bot.main' | grep -v grep")
print(stdout.read().decode('utf-8'))

print("\nService status (active/inactive):")
stdin, stdout, stderr = ssh.exec_command("systemctl is-active booking-bot")
print(stdout.read().decode('utf-8'))

print("\nRecent logs:")
stdin, stdout, stderr = ssh.exec_command("journalctl -u booking-bot -n 15 --no-pager 2>&1")
output = stdout.read().decode('utf-8', errors='replace')
for line in output.split('\n'):
    # Remove special characters
    clean = ''.join(c if ord(c) < 128 else '?' for c in line)
    print(clean)

ssh.close()
