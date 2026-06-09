# ICM Case 6-11 Sequence

Run these cases strictly in order:

1. `TC-ICM-006` - create device record
2. `TC-ICM-007` - bind device to server
3. `TC-ICM-008` - create user
4. `TC-ICM-009` - bind server and device to user
5. `TC-ICM-010` - open remote desktop from screen wall
6. `TC-ICM-011` - cleanup user and device bindings

## Order Rules

- Do not run `TC-ICM-007` before `TC-ICM-006`.
- Do not run `TC-ICM-009` before `TC-ICM-006` to `TC-ICM-008`.
- Do not run `TC-ICM-010` before `TC-ICM-009`.
- Do not run `TC-ICM-011` before `TC-ICM-010`.

## Shared Names

- Device: `Test_Ins01`
- Server: `Test Server#203`
- User: `Tester`
- Admin password: `Hubble_Service!1088`
- Device VNC password: `BCService`

## Batch Notes

- Treat the six cases as one end-to-end business chain.
- Keep the same names unchanged across all six cases.
- If any earlier case fails, stop the batch and hand off from that point.
