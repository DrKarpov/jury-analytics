# DeDust CPMM v2 — verified review cases, not installed classifications

28.11.2026. Wallet Agent inspected real transactions and current pool getters; historical raw trace and message-hash replay still required. These examples are a protocol discovery checkpoint, not a whitelist or economic ledger.

Official ABI: https://hub-beta.dedust.io/docs/cpmm-v2/reference/pool ; liquidity workflow: https://hub-beta.dedust.io/docs/cpmm-v2/quickstart/liquidity-provisioning . `PayNative` (0xa5a7cbf8) and `PayJetton` (0xcbc33949) are shared envelopes; only payment payload, successful settlement and endpoint asset checks distinguish swap, deposit and rewards. `Withdraw` (0x20b5ef89) requests exit; `ExitLiquidity` (0xf6f6a3aa) is the position callback; `JoinLiquidity` (0x25251ee0) finalizes deposit; `RefundDeposit` (0x0d299e12) and fee/reward claims are separate. Withdrawal can include accrued fees, so do not attribute the entire payout as principal without decoded callback amounts.

## Observed traces

| Trace | Observed fact |
|---|---|
| [01fea2c5](https://tonviewer.com/transaction/01fea2c5366c33557305140d44a8a4c3f4753d841bba83bcdef4993be7db8b92) | Owner sent 0.15 TON attached to Withdraw. Pool callback transaction 3528ee5e70fccdc3c2ec9ba6befed6f6130f0634d999464dc6637c94e35af1eb received ExitLiquidity and sent token transfer instruction, native payment 1.829243772 TON, and excess 0.095874320 TON. TonAPI event reports 6.127534220 JURY received. |
| [04658298](https://tonviewer.com/transaction/04658298b5f0991933c166f30a397018833fea9bffaa8caee42ae5fffab17ffe) | Same Withdraw → ExitLiquidity sequence, pool callback 586665b4960b7f489d29986f42ce6cfcd6025d1793b493c7c1c9aafb243b73aa. Event reports 100.008520377 JURY received, native payout 26.638619184 TON and excess 0.095895656 TON. |
| [03fc5a56](https://tonviewer.com/transaction/03fc5a56cf18f9947f3f213b6cbe61c8cb331051bfa655a750c1a6574d1b0d10) | Root sent 101.879396517 TON attached to PayNative plus jetton instruction. Pool accepted two branches and callback ad91a6fd9767c818d8b87e7249e214b29e328f7a97b471fb1d7e6fcbb8d4fc41 received JoinLiquidity. Event reports 359.180480841 JURY sent and 0.000000003 JURY returned; net JURY movement 359.180480838. Native excess and position settlement are separate. |

All three occur in unresolved rows of seed/liquidity.json; independent Wallet Agent event labels are generic SmartContractExec/JettonTransfer/TonTransfer. All three target pools currently have code hash uhYi2FJo2n+jnPwJ31wGnpBImcxlIr+X0dNEP8idDsY= and successful get_pool_data results containing JURY master. Current code hash/getter is NOT proof of historical code or position ownership; prove these with historical transactions. Pools: UQBKkUTE675HzYjRrm-Daxlnk3F-8vDUt79lFhqJG3jfaGlP, UQBq_9P_SqmGSLksqkWsRISWKJ2diWZYfmNHuEzQVHdskBEn (current reserves reported zero), UQBSjZLmojVcR7c8rMmvWNkhju4gWD-Klt0QnsUUIZMcabET. Getter output truncated by connector, so no claim about complete pool state.

## Implementation acceptance

Collect complete raw trees, compare actual historical code hashes and message hashes/endpoints, decode payloads and callback amounts, bind owner/master and pool position, establish delivery and success, separate principal from fees and excess. Detect all occurrences across history by proven protocol structure rather than by these addresses or trace IDs. Support paired assets arriving in different traces and distinguish pending deposits, cancellation, partial refunds, mixed claims, position withdrawals and failed settlements. Do not remove unresolved flags on opcode alone. Record evidence for every economic leg, forbid double-counting in trading volume. Add positive and negative fixtures; compare full-historical counts and amounts before promotion.
