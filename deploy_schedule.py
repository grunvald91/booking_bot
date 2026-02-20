import paramiko
import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Server credentials
host = '155.212.162.47'
user = 'root'
password = 'Booking2025'
remote_base = '/root/booking_bot'
local_base = 'C:/Users/User/booking_bot'

# Files to upload
files = [
    'webapp/server.py',
    'webapp/templates/analytics.html',
    'webapp/templates/schedule.html',
    'webapp/static/js/analytics.js',
    'webapp/static/js/schedule.js',
    'webapp/static/css/analytics.css',
    'webapp/static/css/schedule.css',
    'bot/keyboards/admin_kb.py',
]

# Connect
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, username=user, password=password)
sftp = ssh.open_sftp()

print('Connected to server')

# Upload files
for file_path in files:
    full_local = os.path.join(local_base, file_path)
    full_remote = f'{remote_base}/{file_path}'

    # Create directory if needed
    remote_dir = os.path.dirname(full_remote)
    try:
        sftp.stat(remote_dir)
    except:
        stdin, stdout, stderr = ssh.exec_command(f'mkdir -p {remote_dir}')
        stdout.read()

    sftp.put(full_local, full_remote)
    print(f'Uploaded: {file_path}')

# Restart service
print('Restarting booking-bot service...')
stdin, stdout, stderr = ssh.exec_command('systemctl restart booking-bot')
exit_code = stdout.channel.recv_exit_status()
err = stderr.read().decode('utf-8', errors='replace')
if exit_code == 0:
    print('Service restarted successfully')
else:
    print(f'Restart error: {err}')

sftp.close()
ssh.close()
print('Done!')
