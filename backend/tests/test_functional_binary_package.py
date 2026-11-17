import json
import subprocess
from pathlib import Path
import dingofs_platform.tool_packages as package


def test_functional_bundle_includes_actual_binary_launchers(tmp_path):
    source=Path('/mnt/disk5/daigy/dingofs-testsuite-tool')
    if not source.is_dir():
        import pytest
        pytest.skip('source checkout not mounted')
    helper=Path(package.__file__).parent/'automatic_helper.py'
    script='REQUEST='+repr({'operation':'source_files','directory':str(source),'tool':'dtt'})+'\n'+helper.read_text()
    result=subprocess.run(['python3','-c',script],capture_output=True,text=True,check=True)
    files=json.loads(result.stdout)['files']
    for name in ('env_setup.py','command_utils.py','mount_subdir_executor.py','cache_node_executor.py','trash_executor.py'):
        assert name in files
