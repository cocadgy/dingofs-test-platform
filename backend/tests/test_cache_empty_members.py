import pytest
from dingofs_platform.resources import remote_helper as h

def test_success_with_omitted_members_is_empty(monkeypatch):
    monkeypatch.setattr(h,'run_command',lambda *a,**kw:{'error':{'code':0},'result':{'info':{'cache':{}}}})
    assert h.member_list({'mds_addr':'mds:6900'}) == []

@pytest.mark.parametrize('reply',[{}, {'result':None}, {'result':{'members':None}}, {'result':{'members':{}}}])
def test_malformed_responses_are_not_empty_lists(monkeypatch,reply):
    monkeypatch.setattr(h,'run_command',lambda *a,**kw:reply)
    with pytest.raises(ValueError): h.member_list({'mds_addr':'mds:6900'})
