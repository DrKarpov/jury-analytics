import unittest
from test_indexer import H
from liquidity_proof import verify,POOL_CODE,WITHDRAW,POSITION_WITHDRAW,EXIT,TRANSFER,INTERNAL

def addr(x):return '0:'+H(x)
def node(name,a,i,src=None,opcode=None,b=None):
    m=None if src is None else {'hash':H(name+'m'),'msg_type':'int_msg','source':{'address':addr(src)},'destination':{'address':addr(a)},'op_code':opcode,'bounced':False,'created_lt':str(i-1),'decoded_body':b or {}}
    return {'transaction':{'hash':H(name),'account':{'address':addr(a)},'lt':str(i),'utime':100,'success':True,'aborted':False,'in_msg':m},'children':[]}
def fixture():
    root=node('root','owner',2)
    request=node('request','pool',4,'owner',WITHDRAW)
    pos=node('pos','pos',6,'pool',POSITION_WITHDRAW)
    cb=node('cb','pool',8,'pos',EXIT)
    tr=node('tr','poolwallet',10,'pool',TRANSFER,{'query_id':'5','amount':'12','destination':addr('owner')})
    rx=node('rx','ownerwallet',12,'poolwallet',INTERNAL,{'query_id':'5','amount':'12','from':addr('pool')})
    for a,b in zip([root,request,pos,cb,tr],[request,pos,cb,tr,rx]):a['children']=[b]
    raw={'transactions':[{'hash':H('cb'),'lt':'8','now':100,'account':addr('pool'),'emulated':False,'finality':'finalized','description':{'aborted':False},'account_state_before':{'code_hash':POOL_CODE},'account_state_after':{'code_hash':POOL_CODE},'in_msg':{'hash':H('cbm'),'opcode':EXIT}}]}
    rows=[{'tx':H('tr'),'lt':'10','time':100,'source':addr('pool'),'destination':addr('owner'),'amount_raw':'12','aborted':False}]
    return root,rows,{H('cb'):raw},rx

class LiquidityProofTest(unittest.TestCase):
    def test_withdrawal_payout_is_not_swap(self):
        tree,rows,pools,_=fixture()
        r=verify(H('root'),rows,tree,pools)
        self.assertEqual(r[0]['kind'],'lp_withdraw')
        self.assertEqual(r[0]['legs'][0]['amount_raw'],'12')
    def test_bad_amount(self):
        tree,rows,pools,rx=fixture()
        rx['transaction']['in_msg']['decoded_body']['amount']='13'
        with self.assertRaises(ValueError):verify(H('root'),rows,tree,pools)
    def test_wrong_historical_code(self):
        tree,rows,pools,_=fixture()
        pools[H('cb')]['transactions'][0]['account_state_before']['code_hash']=H('wrong')
        with self.assertRaises(ValueError):verify(H('root'),rows,tree,pools)
    def test_failed_delivery(self):
        tree,rows,pools,rx=fixture()
        rx['transaction']['aborted']=True
        with self.assertRaises(ValueError):verify(H('root'),rows,tree,pools)
