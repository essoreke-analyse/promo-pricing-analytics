# Data quality log

Checks are in `sql/02_quality_checks.sql` and run on the raw transaction table (524,950 rows).

| Check | Result | Decision |
| --- | --- | --- |
| Duplicate week × store × product keys | 0 | — |
| Transactions with unknown store or product | 0 | joins are safe |
| Products / stores in lookups but never sold | 3 of 58 products, 2 of 79 stores | ignored |
| Missing or non-positive shelf price | 24 rows | **excluded** from `sales` |
| Missing base price | 185 rows | **excluded** (discount depth cannot be computed) |
| Non-positive units | 5 rows | **excluded** (log of units undefined) |
| Shelf price > 105 % of base price | 2,066 rows | kept, flagged; sensitivity test in notebook 02 |
| More baskets (VISITS) than units | 2,309 rows | kept, flagged — logically impossible, probably a recording issue; does not affect units or price |
| Spend ≠ units × price (> 5 % gap) | 0 | — |
| Store × product series covering all 156 weeks | 1,225 of 3,909 (median 149 weeks) | models must handle gaps; no imputation |
| Weeks with missing stores | none — 76 to 77 stores every week | dips in weekly totals are real |
| Promo flags | TPR only never combined with feature or display | mechanic defined as Feature + Display / Feature / Display / TPR only / No promo |

Rows kept in the `sales` table: 524,741.
