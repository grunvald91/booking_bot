#!/usr/bin/env python3
"""Complete deployment script - creates archive and deploys to server"""
import paramiko
import os
import sys
import time
import subprocess

# Server credentials
HOST = "155.212.162.47"
USER = "root"
PASSWORD = "***REMOVED***"
REMOTE_PATH = "/opt/booking_bot"

def create_archive():
    """Create deployment archive"""
    print("=" * 60)
    print("STEP 1: Creating deployment archive")
    print("=" * 60)

    result = subprocess.run([sys.executable, "create_deploy_archive.py"],
                          capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("Error creating archive:", result.stderr)
        return False
    return True

def deploy():
    """Deploy to server"""
    print("\n" + "=" * 60)
    print("STEP 2: Deploying to server")
    print("=" * 60)

    archive_name = "deploy_update.tar.gz"

    if not os.path.exists(archive_name):
        print(f"Error: {archive_name} not found!")
        return False

    print(f"\nConnecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
        print("Connected!")

        # Upload archive
        print("\nUploading archive...")
        sftp = ssh.open_sftp()
        sftp.put(archive_name, f"{REMOTE_PATH}/{archive_name}")
        sftp.close()
        print("Archive uploaded!")

        # Stop the bot
        print("\nStopping bot service...")
        stdin, stdout, stderr = ssh.exec_command("systemctl stop booking-bot")
        stdout.channel.recv_exit_status()
        print("Bot stopped.")

        # Backup current files
        print("\nCreating backup...")
        ssh.exec_command(f"cd {REMOTE_PATH} && cp -r bot bot.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true")

        # Extract archive
        print("\nExtracting new files...")
        stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_PATH} && tar -xzf {archive_name}")
        stdout.channel.recv_exit_status()
        print("Files extracted.")

        # Clean up archive
        ssh.exec_command(f"rm {REMOTE_PATH}/{archive_name}")

        # Restart bot
        print("\nRestarting bot service...")
        stdin, stdout, stderr = ssh.exec_command("systemctl restart booking-bot")
        stdout.channel.recv_exit_status()

        # Wait for bot to start
        time.sleep(3)

        # Check if running
        print("\nChecking bot status...")
        stdin, stdout, stderr = ssh.exec_command('ps aux | grep "python.*bot.main" | grep -v grep')
        ps_output = stdout.read().decode().strip()

        if ps_output:
            print("\n" + "=" * 60)
            print("SUCCESS: Bot is running!")
            print("=" * 60)
            print(ps_output)
            return True
        else:
            print("\n" + "=" * 60)
            print("WARNING: Bot may not be running!")
            print("=" * 60)
            stdin, stdout, stderr = ssh.exec_command("journalctl -u booking-bot -n 20 --no-pager")
            logs = stdout.read().decode()
            print("\nLast 20 log lines:")
            print(logs)
            return False

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        ssh.close()

if __name__ == "__main__":
    os.chdir(r"C:\Users\User\booking_bot")

    print("\n" + "=" * 60)
    print("BOOKING BOT DEPLOYMENT")
    print("=" * 60)

    if not create_archive():
        print("\nDeployment aborted: failed to create archive")
        sys.exit(1)

    if not deploy():
        print("\nDeployment completed with warnings")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETED SUCCESSFULLY!")
    print("=" * 60)
