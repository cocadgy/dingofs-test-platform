"""Pure rerun selection gates; database/service integration added after shared release."""
from types import SimpleNamespace

import pytest

from dingofs_platform.errors import Problem


def frozen():
    parent = SimpleNamespace(id='original', state='failed', cancel_requested=False,
        snapshot={'name': 'original', 'cluster_id': 'cluster', 'catalog_digest': 'a' * 64,
            'timeout_minutes': 1440, 'retries': 0, 'module_plans': [
                {'module': 'quota', 'environment_profile_id': 'env', 'environment_profile_revision': 1,
                 'cases': ['failed.yaml', 'never.yaml', 'passed.yaml']},
                {'module': 'client', 'environment_profile_id': 'env', 'environment_profile_revision': 1,
                 'cases': ['later.yaml']}]})
    first = SimpleNamespace(module='quota', state='failed', launch_attempted_at=object(),
        cases=['failed.yaml', 'never.yaml', 'passed.yaml'], result={
            'end_proof': True, 'cleanup_status': 'cleaned', 'recovery_status': 'recovered',
            'retained_resources': [], 'failed_cases': ['failed.yaml'], 'missing': [], 'not_run': ['never.yaml'],
            'case_results': [{'case_path': 'failed.yaml', 'status': 'FAIL'},
                             {'case_path': 'passed.yaml', 'status': 'PASS'}]})
    second = SimpleNamespace(module='client', state='not_run', launch_attempted_at=None,
                             cases=['later.yaml'], result={})
    return parent, [first, second]


def test_rerun_failed_only_excludes_not_run_and_source_drift():
    from dingofs_platform.functional.reruns import rerun_spec, require_same_source
    parent, children = frozen()
    spec = rerun_spec(parent, children, failed_only=True)
    assert [(p.module, p.cases) for p in spec.module_plans] == [('quota', ['failed.yaml'])]
    with pytest.raises(Problem) as exc:
        require_same_source({'catalog_digest': 'a'}, {'catalog_digest': 'b'})
    assert exc.value.status == 409


@pytest.mark.parametrize('state', ['unknown', 'running', 'cancelling', 'cancelled', 'needs_attention'])
def test_unresolved_or_cancelled_parent_cannot_rerun(state):
    from dingofs_platform.functional.reruns import rerun_spec
    parent, children = frozen()
    parent.state = state
    with pytest.raises(Problem) as exc:
        rerun_spec(parent, children, failed_only=False)
    assert exc.value.status == 409


@pytest.mark.parametrize('key,value', [('end_proof', False), ('cleanup_status', 'unknown'),
    ('recovery_status', 'failed'), ('retained_resources', [{'id': 'remaining'}])])
def test_rerun_refuses_unverified_child_even_with_terminal_parent(key, value):
    from dingofs_platform.functional.reruns import rerun_spec
    parent, children = frozen()
    children[0].result[key] = value
    with pytest.raises(Problem) as exc:
        rerun_spec(parent, children, failed_only=True)
    assert exc.value.status == 409


def test_failed_case_list_alone_cannot_promote_not_run():
    from dingofs_platform.functional.reruns import rerun_spec
    parent, children = frozen()
    children[0].result['failed_cases'] = ['never.yaml']
    with pytest.raises(Problem):
        rerun_spec(parent, children, failed_only=True)


def test_reused_confirmation_must_be_subset_of_original_consumed_acknowledgement():
    from dingofs_platform.functional.reruns import confirmed_rerun_impacts
    assert confirmed_rerun_impacts(['known', 'other'], ['known']) == ['known']
    for old, new in [(None, ['known']), (['known'], ['changed']), ([], ['known'])]:
        with pytest.raises(Problem) as exc:
            confirmed_rerun_impacts(old, new)
        assert exc.value.status == 409
