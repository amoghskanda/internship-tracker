#!/usr/bin/env python3
"""Install or remove the local tracker website as a user launch agent."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
label = 'com.internship-runner.dashboard'
plist = Path.home() / 'Library' / 'LaunchAgents' / (label + '.plist')
domain = f'gui/{os.getuid()}'
if len(sys.argv) != 2 or sys.argv[1] not in {'install', 'uninstall'}:
    raise SystemExit('Usage: install_dashboard.py install|uninstall')
if sys.argv[1] == 'uninstall':
    if plist.exists():
        subprocess.run(['launchctl', 'bootout', domain, str(plist)], check=False)
        plist.unlink()
    raise SystemExit(0)
logs = root / 'data' / 'logs'
logs.mkdir(parents=True, exist_ok=True)
plist.parent.mkdir(parents=True, exist_ok=True)
settings = {'Label': label, 'ProgramArguments': [sys.executable, '-m', 'scheduler', '--config', str(root / 'config.json'), 'serve'], 'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10, 'ProcessType': 'Background', 'StandardOutPath': str(logs / 'dashboard.stdout.log'), 'StandardErrorPath': str(logs / 'dashboard.stderr.log')}
if plist.exists():
    subprocess.run(['launchctl', 'bootout', domain, str(plist)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
tmp = plist.with_suffix('.tmp')
tmp.write_bytes(plistlib.dumps(settings))
os.replace(tmp, plist)
subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
print('Local website installed at http://127.0.0.1:8765')
