from types import SimpleNamespace
import pytest
from dingofs_platform.errors import Problem
from dingofs_platform.resources import service


def test_invalid_cache_field_is_identified_without_echoing_value():
    with pytest.raises(Problem) as raised:
        service.create(None, None, SimpleNamespace(action='cache.create', parameters={'group_name':'bad secret name','members':[]}))
    assert raised.value.status == 422
    assert 'group_name' in raised.value.message
    assert 'bad secret name' not in raised.value.message
