import pytest

from dingofs_platform.tool_packages.functional_bundle import FUNCTIONAL_FEATURES, FUNCTIONAL_REQUIRED, functional_capability


def image_bundle():
    return {'tool':'dtt', 'source_location':'image', 'image_id':'sha256:'+'a'*64,
        'files':{'functional_runtime.py':'b'*64}, 'functional_features':FUNCTIONAL_FEATURES,
        'source_manifest':{name:'c'*64 for name in FUNCTIONAL_REQUIRED+['functional_protocol.json','conf/a.yaml','testcases/a.yaml']}}


def test_image_capability_accepts_virtual_sources_only_explicitly():
    bundle=image_bundle()
    assert functional_capability(bundle)['source_manifest']==bundle['source_manifest']
    del bundle['source_location']
    with pytest.raises(ValueError):functional_capability(bundle)


@pytest.mark.parametrize('name,sha',[('../escape','a'*64),('/absolute','a'*64),('src/a.py','bad')])
def test_image_capability_rejects_bad_source_paths_and_hashes(name,sha):
    bundle=image_bundle();bundle['source_manifest'][name]=sha
    with pytest.raises(ValueError):functional_capability(bundle)


def test_source_mode_api():
    from dingofs_platform.tool_packages.routes import JobInput
    assert JobInput(action='auto_install',tool='dtt').source_mode=='directory'
    assert JobInput(action='auto_install',tool='dtt',source_mode='image').source_mode=='image'
    for args in ({'action':'check','tool':'dtt'}, {'action':'auto_install','tool':'dingo'}):
        with pytest.raises(ValueError):JobInput(**args,source_mode='image')
    for mode in (None,1,True,'other'):
        with pytest.raises(ValueError):JobInput(action='auto_install',tool='dtt',source_mode=mode)
