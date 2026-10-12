import pytest
from dingofs_platform.cache_profiles.catalog import validate_options, member_defaults
from dingofs_platform.resources import remote_helper as h

def test_profile_id_is_optional_and_maps_to_member():
    assert member_defaults(validate_options({'id':'cache-a'})) == {'member_id':'cache-a'}
    assert member_defaults(validate_options({'id':''})) == {'member_id':''}

@pytest.mark.parametrize('value',['../x','a/b','a b','--flag'])
def test_id_rejects_unsafe_path_parts(value):
    with pytest.raises(ValueError): validate_options({'id':value})

def test_existing_uuid_rejected_before_port_selection(monkeypatch):
    monkeypatch.setattr(h,'member_list',lambda req:[{'member_id':'chosen','ip':'127.0.0.1','port':21000}])
    with pytest.raises(ValueError,match='ID'):
        h.select_cache_port({'record':{'member_id':'chosen','listen_ip':'127.0.0.1','listen_port':21001}})


def test_prepare_uses_custom_id_for_record_and_directory(monkeypatch):
    from types import SimpleNamespace as NS
    from dingofs_platform.resources import service
    monkeypatch.setattr(service,'step',lambda *args,**kw:kw)
    monkeypatch.setattr(service.port_planning,'reserve',lambda *args:None)
    db=NS(scalars=lambda q:[],add=lambda r:None,flush=lambda:None)
    params={'group_name':'g','members':[{'member_id':'chosen','machine_id':'machine','target_user':'root','listen_port':21000,'cache_dir':'/mnt/cache'}]}
    _,resource=service.prepare(db,NS(id='actor'),NS(id='cluster'),'cache.create',params)
    row=resource.data['members'][0]
    assert row['member_id']=='chosen'
    assert row['cache_dir']=='/mnt/cache/chosen'
