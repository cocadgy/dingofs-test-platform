from pathlib import Path
import re
import pytest
from dingofs_platform.mount_profiles.catalog import CATALOG, validate_options
from dingofs_platform.resources import commands, remote_helper as h
from test_resource_api import runner # noqa
from conftest import linked
from test_storage_profiles import login


def test_catalog_exactly_matches_client_help():
    help_text=(Path(__file__).parents[2]/'docs/reference/dingo-client-main-fe4384a0b-help.txt').read_text()
    names=re.findall(r'^  --(\w+)=',help_text,re.M)
    assert len(names)==193
    assert set(names)=={row['name'] for row in CATALOG}

@pytest.mark.parametrize('p',[{'daemonize':'false'},{'conf':'/tmp/f'},{'fuse_max_threads':'-1'},{'unknown':'x'}])
def test_protected_and_invalid_options_rejected(p):
    with pytest.raises(ValueError): validate_options(p)


def test_mount_command_preserves_options_as_individual_argv():
    args=h.mount_argv({'mds_addr':'mds:6900','record':{'fs_name':'fs','mount_path':'/mnt/fs','log_dir':'/tmp/log','mount_options':{'fuse_max_threads':'16','log_level':'WARNING'}}})
    assert '--fuse_max_threads=16' in args
    assert '--log_level=WARNING' in args
    assert '--daemonize=true' in args


def test_profile_crud_and_mount_snapshot(admin,app,runner):
    p=admin.post('/api/v1/mount-profiles',json={'name':'mount-base','parameters':{'fuse_max_threads':'16'}})
    assert p.status_code==201,p.text
    profile=p.json()
    m,c,_=linked(admin)
    from uuid import uuid4
    params={'machine_id':m['id'],'target_user':'root','fs_name':'fs','mount_path':'/mnt/test-mount',
            'mount_profile_id':profile['id'],'mount_profile_revision':profile['revision']}
    response=admin.post('/api/v1/clusters/'+c['id']+'/resource-operations',json={'action':'mount.create','base_revision':c['revision'],'request_id':str(uuid4()),'confirmed':True,'parameters':params})
    assert response.status_code==202,response.text
    from dingofs_platform.resources.models import ResourceOperation
    with app.state.session_factory() as db:
        op=db.get(ResourceOperation,response.json()['id'])
        assert op.steps[0]['record']['mount_options']=={'fuse_max_threads':'16'}
    bad=admin.put('/api/v1/mount-profiles/'+profile['id'],json={'name':'changed','revision':999,'parameters':{}})
    assert bad.status_code==409
    login(admin,'member')
    assert admin.get('/api/v1/mount-profiles').json()[0]['can_manage'] is False
    assert admin.delete('/api/v1/mount-profiles/'+profile['id']+'?revision=1').status_code==403
