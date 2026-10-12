import json
import sys
from dingofs_platform.resources import remote_helper as helper


def test_actual_commands_are_saved_on_success_and_failure(monkeypatch,capsys):
    def lifecycle(req):
        helper.run_command([sys.executable,'-c','print("ready")'])
        helper.run_command([sys.executable,'-c','import sys; sys.exit(3)'])
    monkeypatch.setattr(helper,'lifecycle',lifecycle)
    helper.main({'action':'cache.create','parameters':{},'record':{},'resource_id':'r'})
    result=json.loads(capsys.readouterr().out)
    assert len(result['executed_commands'])==2
    assert all(row['status']=='started' for row in result['executed_commands'])
    assert 'sys.exit(3)' in result['executed_commands'][1]['command']


def test_launch_trace_uses_actual_final_port(tmp_path,monkeypatch,capsys):
    def lifecycle(req):
        req['record']['listen_port']=21009
        process=helper._launch(req,[sys.executable,'-c','pass','--listen_port=21009'])
        process.wait()
        return 'running',{}
    monkeypatch.setattr(helper,'lifecycle',lifecycle)
    helper.main({'action':'cache.create','parameters':{},'record':{'log_dir':str(tmp_path/'logs'),'listen_port':21000},'resource_id':'r'})
    result=json.loads(capsys.readouterr().out)
    assert '--listen_port=21009' in result['data']['executed_commands'][0]['command']


def test_query_commands_are_traced(monkeypatch,capsys):
    helper.main({'action':'fs.list','parameters':{},'resource_id':'r',
                 'commands':[[sys.executable,'-c','print("listed")']]})
    result=json.loads(capsys.readouterr().out)
    assert result['data']['executed_commands'][0]['status']=='started'


def test_stop_signal_is_traced_as_system_call(monkeypatch,capsys):
    p={'pid':98765,'exe':'/opt/dingo-cache','argv':['dingo-cache'],'start_ticks':'1'}
    states=iter([p,p,None])
    monkeypatch.delattr(helper.os,'pidfd_open',raising=False)
    monkeypatch.setattr(helper,'process_identity',lambda pid:next(states))
    monkeypatch.setattr(helper.os,'kill',lambda *args:None)
    def lifecycle(req):
        helper.stop_recorded_process(p)
        return 'stopped',{'process_stopped':True}
    monkeypatch.setattr(helper,'lifecycle',lifecycle)
    helper.main({'action':'cache.stop','parameters':{},'resource_id':'r'})
    result=json.loads(capsys.readouterr().out)
    trace=result['data']['executed_commands'][0]
    assert trace['command']=='kill -TERM -- 98765'
    assert trace['method']=='os.kill' and trace['status']=='started'
