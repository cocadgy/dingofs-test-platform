"""Target-only extraction of the launcher package from one immutable DTT image.

Executed after functional_bundle.py with REQUEST injected. No source host access.
"""
import platform
import re
import shutil
import subprocess
import tempfile


def image_command(argv, timeout=120):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Image operation failed: ' + ' '.join(argv[:2]) + ': ' + result.stderr.decode(errors='replace')[-2000:])
    return result.stdout.decode()


def extract_image_package(request):
    engine = shutil.which('docker') or shutil.which('podman')
    if not engine:
        raise RuntimeError('Missing Docker/Podman')
    reference = request['image']
    exact_id = bool(re.fullmatch(r'sha256:[0-9a-f]{64}', reference))
    def inspect():
        return json.loads(image_command([engine,'image','inspect',reference]))[0]
    try:
        image = inspect()
    except RuntimeError:
        if exact_id:
            raise RuntimeError('Specified immutable image is not present on target') from None
        image_command([engine,'pull',reference],600)
        image = inspect()
    identifier = image['Id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',identifier) or (exact_id and identifier != reference):
        raise ValueError('Invalid resolved image ID')
    architecture = {'amd64':'x86_64','arm64':'aarch64'}.get(image['Architecture'],image['Architecture'])
    if architecture != platform.machine() or image.get('Os','linux') != 'linux':
        raise ValueError('Image architecture does not match target')
    root = Path.home()/'.local/share/dingofs-platform/staging'
    root.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='image-',dir=root))
    container = None
    try:
        container = image_command([engine,'create','--network=none','--entrypoint','/bin/true',identifier]).strip()
        if not re.fullmatch(r'[0-9a-f]{12,64}',container):
            raise ValueError('Invalid created container ID')
        image_command([engine,'cp',container+':/opt/dtt-platform/.',str(stage)])
    finally:
        if container and re.fullmatch(r'[0-9a-f]{12,64}',container):
            image_command([engine,'rm',container])
    metadata_path = stage/'image-manifest.json'
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise ValueError('Missing image package manifest')
    bundle = json.loads(metadata_path.read_text())
    if (bundle.get('tool') != 'dtt' or bundle.get('source_location') != 'image'
            or bundle.get('architecture') != architecture or not isinstance(bundle.get('files'),dict)
            or bundle.get('entrypoint') != 'dingofs-testsuite-tool'
            or not {'dingofs-testsuite-tool','functional_runtime.py','entrypoint.sh'} <= bundle['files'].keys()):
        raise ValueError('Invalid image package manifest')
    total = 0
    for name, sha in bundle['files'].items():
        if (not isinstance(name,str) or not name or '/' in name or '\\' in name or name in ('.','..','image.tar','manifest.json','image-manifest.json')
                or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha)):
            raise ValueError('Invalid host launcher manifest')
        path = stage/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('Image launcher hash mismatch: '+name)
        total += path.stat().st_size
    if {p.name for p in stage.iterdir()} != set(bundle['files']) | {'image-manifest.json'}:
        raise ValueError('Unexpected files in image launcher package')
    bundle['image_id'] = identifier
    bundle['version'] = identifier
    if functional_capability(bundle) is None:
        raise ValueError('Missing image source manifest')
    bundle['digest'] = hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest()
    bundle['size_bytes'] = total
    (stage/'manifest.json').write_text(json.dumps(bundle))
    return {'staging':str(stage),'bundle':bundle}


if 'REQUEST' in globals():
    print(json.dumps(extract_image_package(REQUEST)))
