"""Command line: run the bot, mint an escrow wallet, or check a deployment."""

from __future__ import annotations

import argparse
import asyncio
import sys

from guarantor import __version__
from guarantor.config import Settings, load_settings
from guarantor.errors import ConfigError
from guarantor.logging import configure
from guarantor.money import format_ton


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guarantor", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run the bot (default)")
    sub.add_parser("new-wallet", help="generate a fresh escrow seed phrase")
    sub.add_parser("doctor", help="check configuration, API access and balance")

    args = parser.parse_args(argv)
    command = args.command or "run"

    try:
        settings = load_settings()
    except Exception as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    configure(settings.log_level)
    try:
        return asyncio.run(_dispatch(command, settings))
    except KeyboardInterrupt:
        return 0
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


async def _dispatch(command: str, settings: Settings) -> int:
    match command:
        case "new-wallet":
            return await _new_wallet(settings)
        case "doctor":
            return await _doctor(settings)
        case _:
            from guarantor.bot.app import Application

            await Application(settings).run()
            return 0


async def _new_wallet(settings: Settings) -> int:
    """Mint a wallet for the escrow and print the seed phrase exactly once.

    The phrase is written to stdout and nowhere else: it is the only thing
    standing between a stranger and every deposit the bot will ever hold.
    """
    from tonutils.contracts import WalletV4R2, WalletV5R1

    from guarantor.ton.client import build_client

    client = build_client(settings)
    wallet_class = WalletV5R1 if settings.escrow_wallet_version == "v5r1" else WalletV4R2
    wallet, _public, _private, mnemonic = wallet_class.create(client, mnemonic_length=24)

    print("network:", settings.ton_network)
    print("wallet: ", settings.escrow_wallet_version)
    print("address:", wallet.address.to_str(is_test_only=settings.is_testnet))
    print()
    print("ESCROW_MNEMONIC=" + " ".join(mnemonic))
    print()
    print("Store this phrase in your secret manager, put it in .env, and never")
    print("commit it. Send this wallet some TON before accepting deals: it pays")
    print("the gas for forwarding NFTs and jettons.")
    return 0


async def _doctor(settings: Settings) -> int:
    """Verify that a deployment would actually work before it holds money."""
    from guarantor.ton.client import TonGateway, build_client
    from guarantor.ton.escrow import EscrowWallet

    problems: list[str] = []
    try:
        settings.validate_runtime()
        print("config:   ok")
    except ConfigError as exc:
        problems.append(str(exc))
        print(f"config:   FAILED — {exc}")

    gateway = TonGateway(settings, build_client(settings))
    await gateway.start()
    try:
        wallet = await EscrowWallet.open(settings, gateway.client)
        print("escrow:  ", wallet.friendly_address())
        balance = await wallet.balance()
        print("balance: ", format_ton(balance))
        if balance < settings.escrow_min_reserve_nano:
            problems.append(
                f"balance {format_ton(balance)} is below the "
                f"{format_ton(settings.escrow_min_reserve_nano)} gas reserve"
            )
        seqno = await wallet.seqno()
        print("seqno:   ", seqno, "(0 means the wallet is not deployed yet)")
    except Exception as exc:
        problems.append(f"TON API: {exc}")
        print(f"ton:      FAILED — {exc}")
    finally:
        await gateway.close()

    if problems:
        print("\nproblems:")
        for problem in problems:
            print(" -", problem)
        return 1
    print("\nall good")
    return 0
