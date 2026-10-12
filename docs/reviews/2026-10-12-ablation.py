from unittest.mock import patch
from types import SimpleNamespace as NS
from datetime import datetime, timezone, timedelta
from dingofs_platform.resources import remote_helper as h, execution as e
from dingofs_platform.mount_profiles import service as profiles
from dingofs_platform.errors import Problem

p=dict(pid=98765,start_ticks='100',exe='/opt/dingo-cache',argv=['dingo-cache','--id=a'])
def identity_case(disable=False):
    sent=[]
    with patch.object(h,'process_identity',side_effect=[{**p,'start_ticks':'200'},None]), patch.object(h.os,'kill',side_effect=lambda *args:sent.append(args)):
        with patch.object(h,'same_process',return_value=True) if disable else patch.object(h,'same_process',wraps=h.same_process):
            try: h._stop_process_compat(p,0)
            except ValueError: pass
    return len(sent)
print('PID reused / signal attempts: baseline=',identity_case(), 'without identity guard=',identity_case(True))
row=NS(id='p',deleted=False,revision=2,enabled=True,parameters={},name='template',source_version='test')
def revision_case(disable=False):
    with patch.object(profiles,'revision',return_value=None) if disable else patch.object(profiles,'revision',wraps=profiles.revision):
        try: profiles.resolve(NS(get=lambda *a:row),'p',1); return 'accepted'
        except Problem: return 'rejected'
print('stale template: baseline=',revision_case(),'without revision guard=',revision_case(True))
a=NS(id='u',disabled=False,role='member'); sess=NS(expires_at=datetime.now(timezone.utc)+timedelta(hours=1),user_id='u')
c=NS(archived=False,binding_state='verified',revision=1,creator_id='other')
op=NS(actor_id='u',session_id='s',cluster_id='c',cluster_revision=1,steps=[])
db=NS(get=lambda model,id: {'u':a,'s':sess,'c':c}[id])
print('foreign cluster operation valid: baseline=',e.valid(db,op),end=' ')
with patch.object(e,'can_manage',return_value=True): print('without ownership guard=',e.valid(db,op))
