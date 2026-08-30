# FlexSys KDS Test History

This is a short map of meaningful historical risks discovered during
Phase 3 development, and the current authoritative test that covers
each one. The Active Test Suite intentionally does not keep every
historical, version-prefixed test around as an archive of development
rounds - overlapping tests covering the same current behavior were
merged, and version/audit-round names were replaced with names that
describe the current product contract. This document exists so that
knowledge of past risks isn't lost in the process.

| Historical issue | Current authoritative coverage |
| --- | --- |
| PostgreSQL claim LIMIT could exceed requested batch | `test_direct_auto_claim_is_server_limited_to_one_job` |
| Expired Direct Auto job could be claimed before cron | `test_expired_pending_job_cannot_be_claimed_and_cron_marks_no_executor` |
| POS session shared by another valid Odoo POS user | `test_shared_pos_session_can_be_used_by_another_valid_pos_user` |
| Wrong POS session token | `test_wrong_pos_session_token_is_rejected` |
| Cross-company POS session access | `test_cross_company_pos_user_cannot_claim_direct_auto_job` |
| POS-only user lacked KDS ACL for payload/result | `test_pos_only_user_claims_direct_auto_job_and_receives_payload` |
| Result RPC failure could allow next print | `test_pos_worker_result_first_blocks_new_claim_until_acknowledged` |
| Session token persistence risk | `test_pos_worker_uses_session_token_without_persisting_it` |
| Rescue session claiming/reporting Direct Auto jobs | `test_rescue_session_cannot_claim_direct_auto_job` |
| Stale result marker from an old session blocking new claims | `test_pos_worker_pending_result_retry_and_stale_session_behavior` |
| `_make_test_pos_config()` fixture leaking wrong-company defaults | `test_make_test_pos_config_respects_company_override` |
| POS line note stored as raw JSON, displayed unnormalized in KDS | `tests/test_note_normalization.py` (whole file) |

Do not turn this document into a development diary - one line per
meaningful historical risk is enough.
