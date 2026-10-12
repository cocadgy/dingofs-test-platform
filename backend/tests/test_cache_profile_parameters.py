from pathlib import Path
import re
import pytest
from dingofs_platform.cache_profiles.catalog import CATALOG, validate_options
from dingofs_platform.resources.remote_helper import cache_argv


def test_complete_help_catalog():
    help_text = (Path(__file__).parents[2] / 'docs/reference/dingo-cache-main-fe4384a0b-help.txt').read_text()
    expected = set(re.findall(r'^  --(\w+)=', help_text, re.M))
    assert {row['name'] for row in CATALOG} == expected
    assert all(row['description'] and row['group'] for row in CATALOG)
    assert next(row for row in CATALOG if row['name']=='cache_eviction')['default']=='2random'

@pytest.mark.parametrize('values', [{'conf':'/tmp/x'}, {'listen_port':'123'}, {'unknown':'x'}, {'shards':'-1'}, {'use_rdma':'yes'}, {'free_space_ratio':'nan'}, {'free_space_ratio':'2'}, {'shards':'4294967296'}, {'cache_eviction':'invalid'}, {'cache_dir':'/tmp'}, {'log_level':'x\ny'}])
def test_invalid_or_managed_options_rejected(values):
    with pytest.raises(ValueError): validate_options(values)

def test_values_are_canonical_and_keep_uint64_precision():
    assert validate_options({'buffer_pool_mb':'18446744073709551615','use_rdma':'false','cache_expire_s':'0','free_space_ratio':'0.1'})['buffer_pool_mb']=='18446744073709551615'


def test_launch_uses_snapshot_once_without_identity_override():
    record = dict(member_id='uuid',group_name='g',listen_ip='192.0.2.1',listen_port=21000,cache_dir='/cache/uuid',cache_size_mb=1024,log_dir='/logs',use_rdma=False,cache_expire_s=0,cache_options={'cache_expire_s':'0','shards':'4','cache_eviction':'lru','s3_region':'test region'})
    argv = cache_argv({'record':record,'mds_addr':'mds:6900'})
    assert '--shards=4' in argv and '--cache_eviction=lru' in argv
    assert '--cache_expire_s=0' in argv and '--s3_region=test region' in argv
    assert len([v for v in argv if v.startswith('--id=')])==1


def test_transmitted_helper_record_preserves_options():
    import json
    import shlex
    from dingofs_platform.resources.commands import build_script
    record=dict(machine_id='machine',target_user='root',member_id='uuid',group_name='group',listen_ip='192.0.2.1',listen_port=21000,cache_dir='/mnt/cache/uuid',cache_size_mb=1024,use_rdma=False,rdma_device='',rdma_port=1,state_dir='/tmp/platform/state',log_dir='/tmp/platform/logs',cache_expire_s=0,cache_options={'cache_expire_s':'0','shards':'4','cache_eviction':'sieve'})
    script=build_script('cache.create',record,'mds:6900','resource',record=record)
    transmitted=json.loads(shlex.split(script)[-1])
    assert '--shards=4' in cache_argv(transmitted)
    assert '--cache_eviction=sieve' in cache_argv(transmitted)
    assert '--cache_expire_s=0' in cache_argv(transmitted)
