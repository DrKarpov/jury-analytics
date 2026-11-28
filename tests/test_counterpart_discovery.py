import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from counterpart_discovery import counterpart,fetch
from genesis_checkpoint import ANCHOR

A='0:'+'a'*64
B='0:'+'b'*64
M={'hash':'11'*32,'source':A,'destination':B,'amount_raw':'10','bounced':False,'token_opcode':'0x178d4519'}
S={'tx':'22'*32,'lt':10,'time':ANCHOR+1,'aborted':False,'alternate_success':True,'in':None,'out':[M]}
R={'tx':'33'*32,'lt':11,'time':ANCHOR+2,'aborted':False,'alternate_success':True,'in':M,'out':[]}
def edge(side):
    row,w,peer=(S,A,B) if side=='outgoing' else (R,B,A)
    return {'side':side,'message':M['hash'],'wallet':w,'peer':peer,'transaction':row['tx'],'lt':str(row['lt']),
            'time':row['time'],'amount_raw':M['amount_raw']}
RAW={'center':{'transactions':[{}]},'alternate':{}}
class CounterpartTests(unittest.TestCase):
    def test_both_directions(self):
        for side,known,other in [('outgoing',S,R),('incoming',R,S)]:
            with patch('counterpart_discovery.compare',return_value=other):
                self.assertEqual(counterpart(edge(side),known,RAW,ANCHOR+5),other)
    def test_reject_bad_counterpart(self):
        for other in ({**R,'in':{**M,'amount_raw':'9'}},{**R,'lt':10},{**R,'aborted':True},{**R,'time':ANCHOR+6}):
            with self.subTest(other=other),patch('counterpart_discovery.compare',return_value=other):
                with self.assertRaises(ValueError):counterpart(edge('outgoing'),S,RAW,ANCHOR+5)
    def test_endpoint_selection(self):
        calls=[]
        def c(ep,params):
            calls.append(('center',ep,params));return {'transactions':[{'hash':S['tx']}]}
        def a(ep,params):
            calls.append(('alternate',ep,params));return {}
        fetch(edge('incoming'),c,a)
        self.assertEqual(calls[0][2]['direction'],'out')
        self.assertEqual(calls[1][1],'blockchain/transactions/'+S['tx'])
        calls.clear();fetch(edge('outgoing'),c,a)
        self.assertEqual(next(x for x in calls if x[0]=='center')[2]['direction'],'in')
        self.assertEqual(next(x for x in calls if x[0]=='alternate')[1],'blockchain/messages/'+M['hash']+'/transaction')
