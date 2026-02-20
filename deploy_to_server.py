#!/usr/bin/env python3
"""Deploy bot updates to server"""
import paramiko
import os

# Server credentials
HOST = "155.212.162.47"
USER = "root"
PASSWORD = "Booking2025"

LOCAL_ARCHIVE = r"C:\Users\User\booking_bot\deploy_update.tar.gz"
REMOTE_PATH = "/opt/booking_bot"

def deploy():
    print(f"Connecting to {HOST}...")

    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
        print("Connected!")

        # Upload archive via SFTP
        print("Uploading archive...")
        sftp = ssh.open_sftp()
        sftp.put(LOCAL_ARCHIVE, f"{REMOTE_PATH}/deploy_update.tar.gz")
        sftp.close()
        print("Archive uploaded!")

        # Stop the bot
        print("\nStopping bot service...")
        stdin, stdout, stderr = ssh.exec_command("systemctl stop booking-bot")
        stdout.channel.recv_exit_status()
        print("Bot stopped.")

        # Backup current files
        print("Creating backup...")
        stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_PATH} && cp -r bot bot.backup 2>/dev/null || true")
        stdout.channel.recv_exit_status()

        # Extract archive
        print("Extracting new files...")
        stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_PATH} && tar -xzvf deploy_update.tar.gz")
        output = stdout.read().decode()
        print(output)

        # Clean up archive
        ssh.exec_command(f"rm {REMOTE_PATH}/deploy_update.tar.gz")

        # Restart bot
        print("\nRestarting bot service...")
        stdin, stdout, stderr = ssh.exec_command("systemctl start booking-bot")
        stdout.channel.recv_exit_status()

        # Wait and check status
        import time
        time.sleep(2)

        print("\nChecking bot status...")
        stdin, stdout, stderr = ssh.exec_command("systemctl status booking-bot")
        print(stdout.read().decode())

        # Check if process is running
        stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'python.*bot.main' | grep -v grep")
        ps_output = stdout.read().decode().strip()
        if ps_output:
            print("✓ Bot is running!")
        else:
            print("⚠ Bot may not be running, check logs!")
            stdin, stdout, stderr = ssh.exec_command("journalctl -u booking-bot -n 20 --no-pager")
            print(stdout.read().decode())

        print("\n=== Deploy completed! ===")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ssh.close()

if __name__ == "__main__":
    deploy()
