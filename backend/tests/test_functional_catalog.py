import json
from pathlib import Path
import pytest
from dingofs_platform.functional.catalog import catalogue, validate_selection


def test_catalog_groups_cases_and_validates_digest(tmp_path):
    root=tmp_path/'testcases';p=root/'quota_test_cases'/'smoke'/'x.yaml';p.parent.mkdir(parents=True)
    p.write_text('case_id: TC-X\ncase_name: small\nrun_level: smoke\ndesc: test\nsteps: []\n')
    data=catalogue(root)
    assert data['modules']['quota'][0]['path']=='smoke/x.yaml'
    chosen=validate_selection(data,{'quota':['smoke/x.yaml']})
    assert chosen=={'quota':['smoke/x.yaml']}
    with pytest.raises(ValueError):validate_selection(data,{'quota':['../x.yaml']})
    p.write_text('case_id: changed\n')
    assert catalogue(root)['digest']!=data['digest']
