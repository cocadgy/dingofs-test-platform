import pytest
from ruamel.yaml import YAML
from dingofs_platform.functional.environments.render import render_environment

@pytest.mark.parametrize('storage',[
 {'storage_type':'s3','s3_ak':'ak','s3_sk':'secret','s3_endpoint':'http://s3','s3_bucketname':'bucket'},
 {'storage_type':'rados','rados_username':'client.a','rados_key':'secret','rados_mon':'10.0.0.1:6789','rados_poolname':'pool','rados_clustername':'ceph'},
])
def test_render_exact_single_environment(storage):
    frozen={'environment_key':'env_platform_123','mds_addr':'10.0.0.1:6900',
            'client_host':'node.test','ssh_user':'tester','settings':{'mount_root':'/tmp/test','fs_prefix':'platform'}}
    document=YAML(typ='safe').load(render_environment(frozen,storage,'sshsecret'))
    assert list(document)==['env_platform_123']
    env=document['env_platform_123']
    assert env['clients'][0]['host']=='node.test'
    assert env['clients'][0]['client_count']==1
    assert env['storage']['storage_type']==storage['storage_type']
    assert env['run_as_user']=='tester/sshsecret'

def test_rejects_unsafe_mount_path_and_unsupported_modules():
    from dingofs_platform.functional.environments.render import validate_custom_settings
    from dingofs_platform.functional.environments.validation import validate_modules
    from dingofs_platform.errors import Problem
    with pytest.raises(ValueError,match='挂载目录'):
        validate_custom_settings({'mount_root':'/tmp/../outside','fs_prefix':'test'})
    with pytest.raises(ValueError,match='文件系统'):
        validate_custom_settings({'mount_root':'/tmp/test','fs_prefix':'bad name'})
    with pytest.raises(Problem):validate_modules({'large_scale_cache':[]})

def test_custom_target_must_match_selected_cluster_and_machine():
    from types import SimpleNamespace
    from dingofs_platform.functional.environments.validation import validate_target
    from dingofs_platform.errors import Problem
    profile=SimpleNamespace(enabled=True,deleted=False,source_kind='custom',cluster_id='c1',machine_id='m1',
        settings={'mount_root':'/tmp/test','fs_prefix':'test'})
    cluster=SimpleNamespace(id='c2',status_snapshot={'mds_addresses':['10.0.0.1:6900']})
    machine=SimpleNamespace(id='m1')
    with pytest.raises(Problem,match='测试环境与目标集群'):
        validate_target(profile,cluster,machine,None,{})

def test_render_clients_and_remote_caches_on_selected_machines():
    frozen={'environment_key':'env_platform_123','mds_addr':'10.0.0.1:6900',
            'client_host':'node-a','ssh_user':'tester',
            'machine_hosts':{'m1':'node-a','m2':'node-b'},
            'settings':{'mount_root':'/tmp/test','fs_prefix':'platform',
                        'clients':[{'machine_id':'m1','client_count':2,'mount_path':'/mnt/test',
                                    'client_conf':{'--cache_store':'disk'}},
                                   {'machine_id':'m2','client_count':1,'mount_path':'/mnt/test2',
                                    'client_conf':{'--cache_group':'group-a'}}],
                        'remote_caches':[{'machine_id':'m2','remote_cache_count':2,
                                          'remote_cache_conf':{'--group_name':'group-a','--cache_dir':'/mnt/cache',
                                                               '--listen_port':12000}}]}}
    storage={'storage_type':'s3','s3_ak':'ak','s3_sk':'secret','s3_endpoint':'http://s3','s3_bucketname':'bucket'}
    env=YAML(typ='safe').load(render_environment(frozen,storage,'sshsecret'))['env_platform_123']
    assert [(c['host'],c['client_count'],c['mount_path']) for c in env['clients']]==[('node-a',2,'/mnt/test'),('node-b',1,'/mnt/test2')]
    assert env['clients'][1]['client_conf']['--cache_group']=='group-a'
    assert env['remote_caches'][0]['host']=='node-b'
    assert env['remote_caches'][0]['remote_cache_count']==2
    assert env['remote_caches'][0]['remote_cache_conf']['--mds_addrs']=='10.0.0.1:6900'

def test_rejects_unsafe_member_configuration():
    from dingofs_platform.functional.environments.service import validate_settings
    from dingofs_platform.errors import Problem
    base={'mount_root':'/tmp/test','fs_prefix':'test'}
    with pytest.raises(Problem):validate_settings({**base,'clients':[{'machine_id':'m1','client_count':0}]})
    with pytest.raises(Problem):validate_settings({**base,'remote_caches':[{'machine_id':'m1','remote_cache_conf':{'--secret':'x'}}]})

def test_member_dingo_path_is_kept_and_mds_address_cannot_be_overridden():
    from dingofs_platform.functional.environments.service import validate_settings
    from dingofs_platform.errors import Problem
    base={'mount_root':'/tmp/test','fs_prefix':'test'}
    validate_settings({**base,'clients':[{'machine_id':'m1','dingo_tool_path':'/opt/dingo/bin/dingo','client_conf':{'--cache_store':'disk'}}]})
    with pytest.raises(Problem):
        validate_settings({**base,'remote_caches':[{'machine_id':'m1','remote_cache_conf':{'--mds_addrs':'evil'}}]})
    with pytest.raises(Problem):
        validate_settings({**base,'remote_caches':[{'machine_id':'m1','remote_cache_conf':{'--access_key':'secret'}}]})

def test_client_parameters_are_flags_not_bare_mds_config_keys():
    frozen={'environment_key':'env_platform_123','mds_addr':'mds:6900','client_host':'node','ssh_user':'tester',
            'settings':{'mount_root':'/tmp/test','fs_prefix':'test'}}
    env=YAML(typ='safe').load(render_environment(frozen,{'storage_type':'s3'},''))['env_platform_123']
    assert all(key.startswith('--') for key in env['clients'][0]['client_conf'])
