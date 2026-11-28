import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from continuation_store import cursor,apply,next_target,select_accounts,post_anchor_frontier,live_negative_focus
from genesis_checkpoint import ANCHOR

W='0:'+'ab'*32
def row(lt):
    return {'lt':lt,'tx':f'{lt:064x}','state_after':f'{lt:064x}'}
def base():
    first=row(1);return {'complete':True,'rows':[first],'prior':(1,first['tx'],first['state_after']),'head':'base'}
def rec(target,head='next'):
    return {'target':target,'digest':head,'observed_at':target+10,'raw':{'tip_center':{'transactions':[{}]},'tip_alternate':{'transactions':[{}]}}}
class PersistentContinuationTests(unittest.TestCase):
    def test_partial_page_continues_same_pinned_tip(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([row(2)],False)),patch('wallet_history.compare',return_value=row(3)):
            p=apply(c,rec(target),W,'master')
        self.assertFalse(p['tip_reached']);self.assertEqual(p['prefix']['prior'][0],2)
        self.assertEqual(next_target(p,target+100),target)
        with patch('continuation_store.replay',return_value=([row(3)],True)),patch('wallet_history.compare',return_value=row(3)):
            q=apply(p,rec(target,'next2'),W,'master')
        self.assertTrue(q['tip_reached']);self.assertEqual(q['new_rows'],[row(2),row(3)])
        self.assertEqual(q['prefix']['head'],'next2');self.assertEqual(next_target(q,target+100),target+100)
        self.assertIsNone(next_target(q,target))
    def test_target_and_tip_change_rejected(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([row(2)],False)),patch('wallet_history.compare',return_value=row(3)):
            p=apply(c,rec(target),W,'master')
        with self.assertRaisesRegex(ValueError,'unfinished pinned target'):
            apply(p,rec(target+1),W,'master')
        with patch('continuation_store.replay',return_value=([row(3)],True)),patch('wallet_history.compare',return_value=row(4)):
            with self.assertRaisesRegex(ValueError,'pinned tip changed'):
                apply(p,rec(target),W,'master')
    def test_completed_target_no_duplicate_or_rollback(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([],True)),patch('wallet_history.compare',return_value=row(1)):
            p=apply(c,rec(target),W,'master')
            with self.assertRaisesRegex(ValueError,'duplicate completed target'):
                apply(p,rec(target),W,'master')
        with self.assertRaisesRegex(ValueError,'target rollback'):
            apply(p,rec(target-1),W,'master')

    def test_refresh_slots_not_starved_by_unseen_accounts(self):
        target=ANCHOR+1000
        states={w:{'rows':[{'time':ANCHOR}]} for w in ('old','partial','new1','new2','new3','blocked')}
        cursors={'old':{'target':ANCHOR+1,'tip_reached':True,'last_observed_at':1,'pages':1},
                 'partial':{'target':ANCHOR+2,'tip_reached':False,'last_observed_at':2,'pages':1}}
        self.assertEqual(select_accounts(set(states),states,cursors,{'blocked':{'at':1000}},target,1200,4),
                         ['partial','new1','old','new2'])
        self.assertEqual(select_accounts({'old'},states,cursors,{},target,1200,4),['old'])
        self.assertEqual(select_accounts({'new1','new2'},states,cursors,{},target,1200,4),['new1','new2'])

    def test_frontier_reports_candidate_without_promoting_it(self):
        a,b,c=('0:'+x*64 for x in ('a','b','c'))
        msg={'hash':'11'*32,'source':a,'destination':b,'amount_raw':'10','bounced':False,'token_opcode':'0x178d4519'}
        s={'tx':'22'*32,'lt':10,'time':ANCHOR+1,'aborted':False,'alternate_success':True,'in':None,'out':[msg]}
        r={'tx':'33'*32,'lt':11,'time':ANCHOR+2,'aborted':False,'alternate_success':True,'in':msg,'out':[]}
        states={a:{'rows':[],'complete':True}}
        f=post_anchor_frontier(states,{a:{'new_rows':[s]}},{a})
        self.assertEqual(f['unmatched_post_anchor_outgoing'],1)
        self.assertEqual(f['peers_not_in_historical_graph'],1)
        self.assertEqual(f['edges'][0]['peer'],b)
        states[b]={'rows':[],'complete':True}
        f=post_anchor_frontier(states,{a:{'new_rows':[s]},b:{'new_rows':[r]}},{a})
        self.assertEqual(f['edges'],[])

    def test_frontier_priority_reserves_only_half_and_honors_backoff(self):
        target=ANCHOR+1000
        states={w:{'rows':[{'time':ANCHOR}]} for w in ('old','hot','hot2','new','blocked')}
        cursors={'old':{'target':ANCHOR+1,'tip_reached':True,'last_observed_at':1,'pages':1}}
        weights={'hot':10,'hot2':9,'blocked':100}
        self.assertEqual(select_accounts(set(states),states,cursors,{'blocked':{'at':1000}},target,1200,4,weights),
                         ['hot','hot2','old','new'])

    def test_negative_inbound_priority_uses_only_eligible_uncovered_peers(self):
        target=ANCHOR+1000
        hints=[{'peer':'need','time':ANCHOR+10},{'peer':'already','time':ANCHOR+10},
               {'peer':'future','time':target+1},{'peer':'unknown','time':ANCHOR+10},
               {'peer':'old','time':ANCHOR}]
        cursors={'already':{'target':ANCHOR+11,'tip_reached':True,'last_observed_at':1,'pages':1}}
        eligible={'need','already','future','old'}
        focus=live_negative_focus(hints,cursors,eligible,target)
        self.assertEqual(focus,{'need':1})
        states={w:{'rows':[{'time':ANCHOR}]} for w in eligible}
        self.assertEqual(select_accounts(eligible,states,cursors,{},target,1200,2,{'old':100},focus)[0],'need')
