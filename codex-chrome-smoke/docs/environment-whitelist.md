# Environment Whitelist

## Allowed Use

This package is for semi-automated browser smoke checks only. It is not for:

- performance testing
- API contract testing
- large unattended CI regression
- unauthorized production data changes

## Required Preflight Checks

Before every run, confirm:

1. Google Chrome is running.
2. Codex Chrome Extension is installed, enabled, and using the correct profile.
3. Codex can discover the `Chrome (extension)` backend.
4. Network, certificate, proxy, SSO, or internal entry conditions are healthy.
5. If file upload is in scope, Chrome has `Allow access to file URLs` enabled.

## Environment Types

### Internal Systems

- Confirm company network, VPN, bastion, or certificate prerequisites first.
- Do not treat a bare `IP:port` as a healthy official entry without validation.
- Reuse existing Chrome login state when the system supports it.

### External Systems

- Prefer test accounts or sandbox environments.
- Production accounts require explicit authorization.
- Payment, approval, mail-send, delete, and other high-risk actions require explicit approval.

## Credentials and Data

- Phase 1 does not include credential vaulting.
- Credentials come from a human operator or an already logged-in Chrome session.
- Any case that changes real business data must state impact and rollback notes in `risk_notes`.

## Blocker Types

- `environment_blocked`
- `login_blocked`
- `ui_blocked`
- `manual_confirmation_required`
