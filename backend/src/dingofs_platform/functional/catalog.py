"""Read-only catalogue of the same YAML tree shipped to the test runner."""
import hashlib
from pathlib import Path
import re

MODULE_DIRS={
 'quota':'quota_test_cases','client':'client_test_cases','cache_node':'cache_node_test_cases',
 'fault':'fault_test_cases','posix':'posix_test_cases','large_scale':'large_scale_test_cases',
 'large_scale_cache':'large_scale_cache_test_cases','mdtest':'mdtest_test_cases',
 'basic_file_operation':'basic_file_operation','mount_subdir':'mount_subdir_test_cases',
 'trash':'trash_test_cases','dirstat':'dirstat_test_cases',
 'hot_upgrade':'hot_upgrade_test_cases','xattr':'xattr_test_cases',
 'warmup':'warmup_test_cases','mds_manage':'mds_manage_test_cases',
 'metadata_consistency':'metadata_consistency_test_cases',
}

def catalogue(root):
    root=Path(root)
    digest=hashlib.sha256();modules={}
    for module,directory in MODULE_DIRS.items():
        base=root/directory
        rows=[]
        for path in sorted(base.rglob('*.yaml')) if base.is_dir() else []:
            if path.is_symlink() or not path.is_file():continue
            relative=path.relative_to(base).as_posix()
            contents=path.read_bytes()
            digest.update(module.encode()+b'\0'+relative.encode()+b'\0'+contents)
            value=contents.decode('utf-8',errors='replace')
            def field(name):
                match=re.search(r'^'+re.escape(name)+r':\s*(.*)$',value,re.M)
                return match[1].strip().strip('"\'') if match else ''
            rows.append({'path':relative,'id':field('case_id') or path.stem,
                         'name':field('case_name') or path.stem,
                         'run_level':field('run_level'),'description':field('desc'),
                         'sha256':hashlib.sha256(contents).hexdigest()})
        if rows:modules[module]=rows
    return {'digest':digest.hexdigest(),'modules':modules}


def validate_selection(data,selection):
    if not isinstance(selection,dict) or not selection:raise ValueError('请至少选择一个用例')
    result={}
    for module,paths in selection.items():
        known={row['path'] for row in data['modules'].get(module,[])}
        if not isinstance(paths,list) or not paths or len(paths)!=len(set(paths)) or not set(paths)<=known:
            raise ValueError('用例清单含不存在、重复或无效路径：'+module)
        result[module]=sorted(paths)
    if 'large_scale' in result and 'large_scale_cache' in result:
        raise ValueError('普通和缓存大规模用例需要分别运行')
    return result
