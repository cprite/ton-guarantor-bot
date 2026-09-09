# Architecture

## Layers

```
bot/          Telegram: handlers, keyboards, i18n, notifications
  ↓ calls
escrow/       the state machine: fees, transitions, the watcher loops
  ↓ calls
ton/          the chain: client, wallet, message parsing, deposit matching
storage/      durable state: deals, seen transfers, the watcher cursor
```

Dependencies point one way. The engine never imports aiogram — it emits
`Event`s and something else decides how to render them, which is why the tests
can drive a complete deal without a Telegram token.

| Module | Responsibility |
|---|---|
| `config.py` | Every operator knob. The only module that reads the environment. |
| `models.py` | `Deal`, `Side`, `Asset`, the status enum. Plain dataclasses that round-trip through JSON. |
| `money.py` | Integer arithmetic in smallest units. No floats anywhere near an amount. |
| `codes.py` | Deal codes and the deposit memos derived from them. |
| `ton/ops.py` | TEP-62 / TEP-74 body parsing. |
| `ton/deposits.py` | Transaction → `IncomingTransfer`, or nothing. |
| `ton/escrow.py` | Signing and broadcasting; the seqno bookkeeping. |
| `escrow/engine.py` | Every transition a deal can make. The only place money moves. |
| `escrow/watcher.py` | The poll loop and the sweep loop. |
| `storage/sqlite.py` | JSON document per deal, plus the columns the watcher queries on. |

## Three problems worth explaining

### 1. Matching a deposit to a deal

An escrow wallet receives transfers from strangers. Each has to be attributed to
exactly one side of one deal, and an attacker must not be able to make the bot
credit a deal they did not fund.

- **NFT.** The deal stores the item address. A deposit is credited only when the
  `ownership_assigned` message came *from that item contract*. Anyone can deploy
  a contract that emits the same opcode, but it will not have the address the
  deal names.
- **Jetton.** When the deal is created, the escrow's own jetton wallet for that
  master is resolved and stored. A `transfer_notification` is credited only when
  it came from that wallet, which only the real jetton master can deploy.
- **TON.** A plain transfer carries no provenance, so it is matched on the
  deposit comment `G-<code>-<A|B>`. Sending TON with somebody else's memo means
  funding their deal, which is not an attack anyone benefits from.

Every credited transfer is recorded by `lt:hash` first, so re-polling the same
window — after a restart, or when the API returns overlapping pages — cannot
credit it twice.

### 2. Paying out without paying twice

A payout is a signed external message. If the process dies between broadcasting
and recording the result, a naive retry pays everyone twice.

The wallet is single-signer, which makes `seqno` a reliable witness:

1. Read `seqno`, pin `valid_until = now + 120s`, sign.
2. **Persist** `(seqno, message hash, sent_at)` and set the deal to `SETTLING`.
3. Broadcast.
4. Later — in the sweep loop, or on the next start-up — compare:
   - `seqno` advanced → our message was applied. Nothing else could have moved
     it. Mark the deal complete.
   - `seqno` unchanged and `valid_until` is past → the message can never be
     applied. Rebuild and resend.
   - otherwise → still undecided; look again next sweep.

After `MAX_SETTLE_ATTEMPTS` rebuilds the deal goes to `FAILED`, both parties are
told their funds are still held, and the operator is alerted. The bot stops
rather than improvising.

Signing is serialised by a lock: two coroutines that both signed for the same
seqno would produce two messages of which the network silently applies one.

### 3. Where a payout goes

Nobody types an address. Each side's payout address is the wallet that funded
their side — taken from the sender of the TON transfer, the `prev_owner` of the
NFT, or the `sender` in the jetton notification. A refund therefore always
returns to its origin, and a swap always lands somewhere the recipient
demonstrably controls.

The exception is a party whose own leg is off-chain: they never deposit, so they
supply an address with `/address <code> <wallet>`.

## Concurrency

The two loops and the Telegram handlers all mutate deals. Every transition is
serialised by a per-deal `asyncio.Lock`, and each critical section re-reads the
deal inside the lock rather than trusting the copy it was handed. SQLite runs in
WAL mode with a single connection and a write lock.

The state machine tolerates the orders the real world produces: a deposit
arriving for a cancelled deal, both legs landing in the same poll, a settlement
in flight when the process is killed.

## What is deliberately not here

- **An on-chain escrow contract.** The custody model is a hot wallet. A
  contract-based escrow removes the operator's ability to steal, and is the
  natural next version — but it is a different security model, not a setting.
- **A general dispute protocol.** Arbitration is the operator's judgement, with
  commands to act on it.
- **Price feeds.** The bot never decides whether a deal is fair, only whether
  both sides delivered what they promised.
