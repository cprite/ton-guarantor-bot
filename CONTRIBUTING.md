# Contributing

Bug reports, translations and pull requests are all welcome.

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make test lint typecheck
```

## Before opening a pull request

- `make test lint typecheck` passes. CI runs the same three on 3.11–3.13.
- Anything that touches how money moves comes with a test. The suite drives the
  real engine over a real database, so a new rule belongs in `tests/test_engine.py`
  rather than in a mock.
- Keep the layering: `bot/` may call `escrow/`, `escrow/` may call `ton/` and
  `storage/`, and nothing below `bot/` imports aiogram.

## Adding a language

1. Copy the `EN` dictionary in `src/guarantor/bot/texts.py`, translate the
   values, and register it in `LOCALES`.
2. Leave the `{placeholders}` and the HTML tags exactly as they are —
   `tests/test_texts.py` checks that every locale matches English structurally,
   and will fail the build if one drifts.

## Adding an asset type

1. Extend `AssetKind` and give `Asset.human()` a branch.
2. Teach `ton/ops.py` to recognise its incoming message, and `ton/deposits.py`
   to turn it into an `IncomingTransfer`.
3. Teach `EscrowEngine._match` how to attribute it to a deal — by the contract
   that sent it, if at all possible, rather than by a comment.
4. Add a payout builder in `EscrowWallet.build_payout`.
5. Add tests at both ends: body parsing, and a full deal in the engine.
