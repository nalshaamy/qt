# FlexSys Operations Architecture

## Current foundation

- `controllers/`: HTTP routes and request/response handling.
- `services/`: application service boundaries and business orchestration.
- `models/`: Odoo persistence and domain records.
- `common/`: small shared helpers with minimal framework coupling.
- `tests/`: automated regression and service tests.

During CORE-003A no existing controller or model behavior is moved. The new
packages are scaffolding only.
