"""Read-only remote checks for a custom integration environment."""
import time
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from dingofs_platform.tool_packages.ssh_session import Remote

PROBE_CODE='''import json,os,shutil,subprocess
from pathlib import Path
root=Path.home()/'.local/share/dingofs-platform/tools/dtt/current'
dtt=root/'dtt'
answer={'dtt':dtt.is_file() and os.access(dtt,os.X_OK),
        'runtime':all((root/name).is_file() for name in ('entrypoint.sh','run_tests.py','test_suite.py','functional_plan.py','env_parser.py','env_setup.py','command_utils.py','mount_subdir_executor.py','trash_executor.py','cache_node_executor.py','hot_upgrade_executor.py','dirstat_executor.py','mds_manage_executor.py','client_mount_ops.py','client_cache_group_ops.py','large_scale_cache_setup.py','large_scale_cache_observer.py')),
        'dingo':(Path(DINGO_PATH).is_file() and os.access(DINGO_PATH,os.X_OK)) if DINGO_PATH else bool(shutil.which('dingo'))}
if (root/'functional-runtime.json').is_file():
    try:
        probe=subprocess.run([str(dtt),'--functional-capabilities','--format','json'],
            capture_output=True,text=True,timeout=60)
        capability=json.loads(probe.stdout) if probe.returncode==0 else {}
        answer['runtime']=capability.get('version')==2 and bool(capability.get('source_manifest'))
    except (OSError,ValueError,subprocess.SubprocessError):answer['runtime']=False
print(json.dumps(answer))
'''
CLIENT_PROBE_CODE='''import json,os,shutil
from pathlib import Path
client=Path.home()/'.dingo/components/dingo-client/main/dingo-client'
if CLIENT_PATH:client=Path(CLIENT_PATH)
mount=Path(MOUNT_ROOT)
parent=mount
while not parent.exists() and parent!=parent.parent:parent=parent.parent
print(json.dumps({'client':(client.is_file() and os.access(client,os.X_OK)) or (not CLIENT_PATH and bool(shutil.which('dingo-client'))),
                  'mount_parent_writable':parent.is_dir() and os.access(parent,os.W_OK|os.X_OK)}))
'''

CACHE_PROBE_CODE='''import json,os,shutil
from pathlib import Path
cache=Path.home()/'.dingo/components/dingo-cache/main/dingo-cache'
if CACHE_PATH:cache=Path(CACHE_PATH)
print(json.dumps({'cache':(cache.is_file() and os.access(cache,os.X_OK)) or (not CACHE_PATH and bool(shutil.which('dingo-cache')))}))
'''

def probe(machine,key,code):
    password=decrypt_password(machine.ssh_password_ciphertext,key)
    config=SSHConfig(machine.address,machine.ssh_port,machine.ssh_user,password)
    remote=Remote(config,time.monotonic()+60,lambda **kw:None,'环境预检')
    try:return remote.python(code,'只读检查')
    finally:remote.close()
