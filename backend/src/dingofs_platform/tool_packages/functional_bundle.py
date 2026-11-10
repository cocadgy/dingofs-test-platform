"""Shared offline/automatic functional bundle policy (stdlib, no source imports)."""
import hashlib
import json
from pathlib import Path

FUNCTIONAL_FEATURES = ['exact_case_plan_v1', 'runtime_context_v1', 'owned_cleanup_v1',
                       'lifecycle_events_v2', 'cancel_boundary_v1', 'inspection_v1']
FUNCTIONAL_REQUIRED = ['run_tests.py', 'requirements.txt', 'pytest.ini',
    'src/test_runner/functional_plan.py', 'src/test_runner/runtime_context.py',
    'src/test_runner/resource_journal.py', 'src/test_runner/owned_resources.py',
    'src/test_runner/functional_events.py', 'src/test_runner/functional_redaction.py',
    'src/test_runner/functional_contracts.py', 'src/test_runner/functional_capabilities.py',
    'src/config/ssh_client.py', 'src/config/env_parser.py']


def functional_source_files(directory):
    """Return package-relative source paths; absent legacy support stays absent."""
    directory = Path(directory)
    if not (directory / 'functional_runtime.py').is_file():
        return {}, {}, {}
    root = directory / 'dingofs-integration-test'
    roots = ('run_tests.py', 'requirements.txt', 'pytest.ini', 'pyproject.toml',
             'setup.cfg', 'setup.py', 'conftest.py', 'functional_protocol.json')
    trees = ('src', 'conf', 'testcases', 'scripts', 'tools', 'template')
    paths = [root / name for name in roots if (root / name).exists()]
    for name in trees:
        tree = root / name
        if tree.is_symlink():
            raise ValueError('functional runtime symlink is forbidden')
        if tree.exists():
            for path in tree.rglob('*'):
                if path.is_symlink():
                    # Repository smoke suites use aliases to sibling case files.
                    # Resolve only regular files inside this same runtime tree;
                    # transfer their bytes under the original relative name.
                    if not path.resolve().is_relative_to(tree.resolve()) or not path.is_file():
                        raise ValueError('functional runtime external/directory symlink is forbidden')
                if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                    paths.append(path)
    for path in paths:
        if any(part.is_symlink() for part in path.parents) or (path.is_symlink() and path.parent==root):
            raise ValueError('functional runtime symlink is forbidden')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths)}
    if not set(FUNCTIONAL_REQUIRED + ['functional_protocol.json']) <= manifest.keys():
        raise ValueError('Incomplete functional runtime protocol files; integrate the verified framework first')
    protocol = json.loads((root / 'functional_protocol.json').read_text())
    if (protocol.get('version') != 2 or protocol.get('context_version') != 1
            or protocol.get('event_version') != 2
            or set(protocol.get('features', [])) != set(FUNCTIONAL_FEATURES)):
        raise ValueError('Unsupported functional runtime protocol')
    if not any(p.startswith('conf/') for p in manifest) or not any(p.startswith('testcases/') for p in manifest):
        raise ValueError('Incomplete functional runtime configuration/cases')
    files = {'dingofs-integration-test/' + name: (root / name).resolve() for name in manifest}
    for name in ('functional_runtime.py', 'entrypoint.sh'):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing functional runtime launcher')
        files[name] = path
    aliases={p.relative_to(root).as_posix():p.resolve().relative_to(root).as_posix()
             for p in paths if p.is_symlink()}
    return files, manifest, aliases


def functional_capability(bundle):
    source = bundle.get('source_manifest')
    if source is None:
        return None
    if (bundle.get('functional_features') != FUNCTIONAL_FEATURES or not isinstance(source, dict)
            or not set(FUNCTIONAL_REQUIRED + ['functional_protocol.json']) <= source.keys()
            or any(bundle['files'].get('dingofs-integration-test/' + name) != sha for name, sha in source.items())):
        raise ValueError('Invalid functional runtime package manifest')
    aliases=bundle.get('source_aliases',{})
    if not isinstance(aliases,dict):
        raise ValueError('Invalid functional source aliases')
    for alias,target in aliases.items():
        if (not isinstance(alias,str) or not isinstance(target,str) or alias==target
                or target in aliases or alias not in source or target not in source
                or source[alias]!=source[target]
                or any(Path(name).is_absolute() or '..' in Path(name).parts for name in (alias,target))):
            raise ValueError('Invalid functional source alias target')
    return {'version': 2, 'features': FUNCTIONAL_FEATURES,
            'files': {name: sha for name, sha in bundle['files'].items() if name != 'image.tar'},
            'image_id': bundle['image_id'], 'source_manifest': source}
