import hashlib
import json
import platform
from pathlib import Path
import pytest
from dingofs_platform.tool_packages import automatic
from dingofs_platform.tool_packages.functional_bundle import FUNCTIONAL_REQUIRED, FUNCTIONAL_FEATURES

IMAGE='sha256:'+'a'*64


def harness(tmp_path, monkeypatch, missing=False, corrupt=False, no_sources=False):
    import subprocess
    monkeypatch.setenv('HOME',str(tmp_path))
    monkeypatch.setattr('shutil.which',lambda _: '/bin/docker')
    calls=[]
    files={name:b'launcher' for name in ['dingofs-testsuite-tool','functional_runtime.py','entrypoint.sh']}
    bundle={'tool':'dtt','architecture':platform.machine(),'entrypoint':'dingofs-testsuite-tool',
        'source_location':'image','files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()},
        'functional_features':FUNCTIONAL_FEATURES,'source_manifest':{n:'b'*64 for n in FUNCTIONAL_REQUIRED+['functional_protocol.json','conf/a','testcases/a']}}
    if no_sources:bundle.pop('source_manifest')
    def run(argv,**kwargs):
        calls.append(argv)
        output=b''; rc=0
        if argv[1:3]==['image','inspect']:
            if missing and not any(c[1]=='pull' for c in calls):rc=1
            else:output=json.dumps([{'Id':IMAGE,'Architecture':platform.machine(),'Os':'linux'}]).encode()
        elif argv[1]=='create':output=('c'*64).encode()
        elif argv[1]=='cp':
            stage=Path(argv[-1]);(stage/'image-manifest.json').write_text(json.dumps(bundle))
            for name,data in files.items():(stage/name).write_bytes(b'bad' if corrupt else data)
        return subprocess.CompletedProcess(argv,rc,output,b'failed')
    monkeypatch.setattr(subprocess,'run',run)
    code=Path(automatic.__file__).with_name('functional_bundle.py').read_text()+'\n'+Path(automatic.__file__).with_name('image_helper.py').read_text()
    ns={};exec(code,ns)
    return ns['extract_image_package'],calls


def test_extract_local_id_pins_package_and_never_pulls(tmp_path,monkeypatch):
    extract,calls=harness(tmp_path,monkeypatch)
    result=extract({'image':IMAGE})
    assert result['bundle']['image_id']==IMAGE
    assert result['bundle']['source_location']=='image'
    assert not any(c[1]=='pull' for c in calls)
    assert next(c for c in calls if c[1]=='create')[-1]==IMAGE
    assert calls[-1]==['/bin/docker','rm','c'*64]


def test_missing_local_id_never_falls_back_to_pull(tmp_path,monkeypatch):
    extract,calls=harness(tmp_path,monkeypatch,missing=True)
    with pytest.raises(RuntimeError,match='not present'):extract({'image':IMAGE})
    assert not any(c[1]=='pull' for c in calls)


def test_named_reference_pulls_only_when_missing(tmp_path,monkeypatch):
    extract,calls=harness(tmp_path,monkeypatch,missing=True)
    assert extract({'image':'registry/dtt:tag'})['bundle']['image_id']==IMAGE
    assert [c for c in calls if c[1]=='pull']==[['/bin/docker','pull','registry/dtt:tag']]


def test_corrupt_launcher_rejected_after_created_container_removed(tmp_path,monkeypatch):
    extract,calls=harness(tmp_path,monkeypatch,corrupt=True)
    with pytest.raises(ValueError,match='hash mismatch'):extract({'image':IMAGE})
    assert calls[-1]==['/bin/docker','rm','c'*64]


def test_image_package_requires_source_manifest(tmp_path,monkeypatch):
    extract,_=harness(tmp_path,monkeypatch,no_sources=True)
    with pytest.raises(ValueError,match='source manifest'):extract({'image':IMAGE})


def test_image_deploy_never_opens_source_or_scp(monkeypatch):
    calls=[]
    class Remote:
        def __init__(self,config,*args):assert config=='target'
        def python(self,code,phase):
            calls.append(code)
            if len(calls)==1:return {'staging':'/stage','bundle':{'tool':'dtt','image_id':IMAGE}}
            if len(calls)==2:return {'installed_path':'/installed'}
            return {'items':[{'tool':'dtt','status':'ready'}]}
        def close(self):pass
    monkeypatch.setattr(automatic,'Remote',Remote)
    monkeypatch.setattr(automatic,'install_script',lambda bundle,stage:'INSTALL')
    monkeypatch.setattr(automatic,'probe_script',lambda:'PROBE')
    result=automatic.deploy('target','forbidden',{'tool':'dtt','source_mode':'image','image':IMAGE},60,lambda **kw:None)
    assert result['image_id']==IMAGE
    assert result['method']=='image'
    assert calls[-2:]==['INSTALL','PROBE']
