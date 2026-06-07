# AnyRouter check-in diagnostic report (sanitized)

- Run: https://github.com/shenhao-stu/anyrouter-check-in/actions/runs/27069907527
- Generated: 2026-06-07T02:24:36
- Summary: total=42, success=16, failed=25, timeouts=1, login_ok=14, login_bad=27
- Secret policy: raw logs are not published; this report redacts api_user/token/cookie/auth-like values.

## Account results

| # | provider | domain | status | login before→after | reason |
|---:|---|---|---|---|---|
| 01 | anyrouter | https://anyrouter.top | success | True→True | success |
| 02 | agentrouter | https://agentrouter.org | success | False→False | success |
| 03 | freestyle | https://api.freestyle.cc.cd | failed | False→False | [FAILED] Account 3: Check-in failed - HTTP 404 |
| 04 | xingyungept | https://ai.xingyungept.cn | failed | False→? | [FAILED] Account 4: Error occurred during check-in process - [Errno -2] Name or service not known |
| 05 | apikey | https://welfare.apikey.cc | failed | False→False | [FAILED] Account 5: Check-in failed - HTTP 522 |
| 06 | crworld | https://api.crworld.site | timeout | ?→? | TIMEOUT after 180s; provider loaded then subprocess hung |
| 07 | anyrouter | https://anyrouter.top | success | True→True | success |
| 08 | anyrouter | https://anyrouter.top | success | True→True | success |
| 09 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 9: Check-in failed - HTTP 401 |
| 10 | anyrouter | https://anyrouter.top | success | True→True | success |
| 11 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 11: Check-in failed - HTTP 401 |
| 12 | anyrouter | https://anyrouter.top | success | True→True | success |
| 13 | anyrouter | https://anyrouter.top | success | True→True | success |
| 14 | anyrouter | https://anyrouter.top | success | True→True | success |
| 15 | anyrouter | https://anyrouter.top | success | True→True | success |
| 16 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 16: Check-in failed - HTTP 401 |
| 17 | anyrouter | https://anyrouter.top | success | True→True | success |
| 18 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 18: Check-in failed - HTTP 401 |
| 19 | elysiver | https://elysiver.h-e.top | failed | False→False | [FAILED] Account 19: Check-in failed - HTTP 401 |
| 20 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 20: Check-in failed - HTTP 401 |
| 21 | anyrouter | https://anyrouter.top | success | True→True | success |
| 22 | anyrouter | https://anyrouter.top | success | True→True | success |
| 23 | anyrouter | https://anyrouter.top | failed | False→False | [FAILED] Account 23: Check-in failed - HTTP 401 |
| 24 | anyrouter | https://anyrouter.top | success | True→True | success |
| 25 | anyrouter | https://anyrouter.top | success | True→True | success |
| 26 | anyrouter | https://anyrouter.top | success | True→True | success |
| 27 | elysiver | https://elysiver.h-e.top | failed | False→False | [FAILED] Account 27: Check-in failed - HTTP 401 |
| 28 | elysiver | https://elysiver.h-e.top | failed | False→False | [FAILED] Account 28: Check-in failed - HTTP 401 |
| 29 | zhenhaoji | https://api.zhenhaoji.qzz.io | failed | False→False | [FAILED] Account 29: Check-in failed - HTTP 401 |
| 30 | zhenhaoji | https://api.zhenhaoji.qzz.io | failed | False→False | [FAILED] Account 30: Check-in failed - HTTP 401 |
| 31 | demo | https://demo.awa1.fun | failed | False→? | [FAILED] Account 31: Error occurred during check-in process - [Errno -2] Name or service not known |
| 32 | computetoken | https://computetoken.ai | failed | False→False | [FAILED] Account 32: Check-in failed - HTTP 401 |
| 33 | zhenhaoji | https://api.zhenhaoji.qzz.io | failed | False→False | [FAILED] Account 33: Check-in failed - HTTP 401 |
| 34 | apikey | https://welfare.apikey.cc | failed | False→False | [FAILED] Account 34: Check-in failed - HTTP 522 |
| 35 | aidrouter | https://aidrouter.qzz.io | failed | False→? | [FAILED] Account 35: Playwright check-in error - Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://aidrouter.qzz.io/ |
| 36 | aidrouter | https://aidrouter.qzz.io | failed | False→? | [FAILED] Account 36: Playwright check-in error - Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://aidrouter.qzz.io/ |
| 37 | daiju | https://api.daiju.live | failed | False→? | [FAILED] Account 37: Error occurred during check-in process - [Errno -5] No address associated with hostname |
| 38 | computetoken | https://computetoken.ai | failed | False→False | [FAILED] Account 38: Check-in failed - HTTP 401 |
| 39 | 42w | https://api.42w.shop | failed | False→False | [FAILED] Account 39: Check-in failed - HTTP 401 |
| 40 | computetoken | https://computetoken.ai | failed | False→False | [FAILED] Account 40: Check-in failed - HTTP 401 |
| 41 | freestyle | https://api.freestyle.cc.cd | failed | False→False | [FAILED] Account 41: Check-in failed - HTTP 404 |
| 42 | agentrouter | https://agentrouter.org | success | False→False | success |

## Failure clusters

- 401 auth/cookie invalid: #09, #11, #16, #18, #19, #20, #23, #27, #28, #29, #30, #32, #33, #38, #39, #40
- 404 endpoint missing: #03, #41
- 522 origin timeout: #05, #34
- DNS resolution: #04, #31, #37
- Playwright/CF page load: #35, #36
- success: #01, #02, #07, #08, #10, #12, #13, #14, #15, #17, #21, #22, #24, #25, #26, #42
- timeout/hang: #06

## Key finding

- The original hanging account is **#06 / provider `crworld` / `https://api.crworld.site`**. It emitted only provider/config-load lines and then exceeded the 180s isolated subprocess timeout.
- The branch now keeps the normal production `checkin.yml` separable from the temporary diagnostic workflow, so a diagnostic PR will not silently replace the scheduled check-in job.