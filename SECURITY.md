# Security policy

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/cprite/ton-guarantor-bot/security/advisories/new)
rather than in a public issue. Include what an attacker gains and the smallest
reproduction you have; a working exploit is not needed.

You will get an acknowledgement within a few days. If you would like credit in
the fix, say so.

## What is in scope

Anything that lets somebody take funds they are not owed, or make the escrow
release before both legs are confirmed. In particular:

- crediting a deposit that was not actually made,
- causing a payout to the wrong address,
- acting on a deal you are not a party to,
- making the escrow pay out twice for the same deal.

## What is known, and not a vulnerability

- **The escrow is custodial.** The operator's key can move every deposit. That
  is the design; see the security model in the README. If you want escrow that
  the operator cannot raid, it needs an on-chain contract.
- **Off-chain legs are not verified.** They are settled by the parties and by
  arbitration, and can be turned off entirely.
- **The operator can arbitrate.** `/award` and `/payout` exist so a human can
  resolve what the automation cannot.

## Running it safely

- Keep `ESCROW_MNEMONIC` in a secret manager, never in git. Rotating it means
  moving the balance to a new wallet.
- Keep escrow balances small: only what live deals need.
- Set `ADMIN_IDS` to accounts with two-factor authentication enabled — a
  compromised operator account is a compromised escrow.
- Back up the database. Losing it does not lose the funds, but it does lose the
  record of who they belong to.
- Rehearse on testnet after every upgrade.
