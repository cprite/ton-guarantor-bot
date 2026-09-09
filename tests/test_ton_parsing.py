"""Parsing real message bodies and transactions the way the chain hands them over."""

from __future__ import annotations

from types import SimpleNamespace

from pytoniq_core import Address, begin_cell
from pytoniq_core.tlb.block import CurrencyCollection
from pytoniq_core.tlb.transaction import ExternalMsgInfo, InternalMsgInfo, MessageAny

from guarantor.ton import addresses as addr
from guarantor.ton.deposits import TransferKind, parse_transaction
from guarantor.ton.ops import (
    OP_JETTON_TRANSFER_NOTIFICATION,
    OP_NFT_OWNERSHIP_ASSIGNED,
    parse_jetton_notification,
    parse_ownership_assigned,
    read_comment,
)

ESCROW = Address("0:" + "e" * 64)
SENDER = Address("0:" + "a" * 64)
NFT = Address("0:" + "1" * 64)
JWALLET = Address("0:" + "3" * 64)


def comment_body(text: str):
    return begin_cell().store_uint(0, 32).store_snake_string(text).end_cell()


def transaction(body, *, src=SENDER, dest=ESCROW, value=10**9, bounced=False, lt=100, external=False):
    if external:
        info = ExternalMsgInfo(src=None, dest=dest, import_fee=0)
    else:
        info = InternalMsgInfo(
            ihr_disabled=True,
            bounce=True,
            bounced=bounced,
            src=src,
            dest=dest,
            value=CurrencyCollection(value),
            ihr_fee=0,
            fwd_fee=0,
            created_lt=lt,
            created_at=1_700_000_000,
        )
    message = MessageAny(info, None, body)
    return SimpleNamespace(
        in_msg=message,
        lt=lt,
        now=1_700_000_000,
        cell=SimpleNamespace(hash=bytes.fromhex("ab" * 32)),
    )


# ------------------------------------------------------------------- bodies


def test_text_comment_round_trip():
    assert read_comment(comment_body("G-ABCDEFGH-A")) == "G-ABCDEFGH-A"


def test_non_comment_bodies_are_not_mistaken_for_comments():
    assert read_comment(begin_cell().store_uint(0x12345678, 32).end_cell()) is None
    assert read_comment(begin_cell().end_cell()) is None
    assert read_comment(None) is None


def test_ownership_assigned_with_inline_payload():
    body = (
        begin_cell()
        .store_uint(OP_NFT_OWNERSHIP_ASSIGNED, 32)
        .store_uint(7, 64)
        .store_address(SENDER)
        .store_bit_int(0)
        .store_uint(0, 32)
        .store_snake_string("G-ABCDEFGH-A")
        .end_cell()
    )
    parsed = parse_ownership_assigned(body)
    assert parsed is not None
    assert addr.same(parsed.previous_owner, SENDER)
    assert parsed.comment == "G-ABCDEFGH-A"


def test_ownership_assigned_with_referenced_payload():
    body = (
        begin_cell()
        .store_uint(OP_NFT_OWNERSHIP_ASSIGNED, 32)
        .store_uint(7, 64)
        .store_address(SENDER)
        .store_bit_int(1)
        .store_ref(comment_body("hello"))
        .end_cell()
    )
    parsed = parse_ownership_assigned(body)
    assert parsed is not None and parsed.comment == "hello"


def test_ownership_assigned_without_a_payload():
    body = (
        begin_cell()
        .store_uint(OP_NFT_OWNERSHIP_ASSIGNED, 32)
        .store_uint(7, 64)
        .store_address(SENDER)
        .store_bit_int(0)
        .end_cell()
    )
    parsed = parse_ownership_assigned(body)
    assert parsed is not None and parsed.comment is None


def test_jetton_notification():
    body = (
        begin_cell()
        .store_uint(OP_JETTON_TRANSFER_NOTIFICATION, 32)
        .store_uint(1, 64)
        .store_coins(1_500_000)
        .store_address(SENDER)
        .store_bit_int(1)
        .store_ref(comment_body("G-ABCDEFGH-B"))
        .end_cell()
    )
    parsed = parse_jetton_notification(body)
    assert parsed is not None
    assert parsed.amount == 1_500_000
    assert parsed.comment == "G-ABCDEFGH-B"
    assert addr.same(parsed.sender, SENDER)


def test_op_parsers_ignore_each_other():
    assert parse_jetton_notification(comment_body("x")) is None
    assert parse_ownership_assigned(comment_body("x")) is None


# -------------------------------------------------------------- transactions


def test_plain_ton_deposit_is_recognised():
    transfer = parse_transaction(transaction(comment_body("G-ABCDEFGH-A")), ESCROW)
    assert transfer is not None
    assert transfer.kind is TransferKind.TON
    assert transfer.comment == "G-ABCDEFGH-A"
    assert transfer.amount == 10**9
    assert addr.same(transfer.depositor, SENDER)


def test_nft_deposit_reports_the_item_as_source_and_the_owner_as_depositor():
    body = (
        begin_cell()
        .store_uint(OP_NFT_OWNERSHIP_ASSIGNED, 32)
        .store_uint(0, 64)
        .store_address(SENDER)
        .store_bit_int(0)
        .end_cell()
    )
    transfer = parse_transaction(transaction(body, src=NFT, value=50_000_000), ESCROW)
    assert transfer is not None
    assert transfer.kind is TransferKind.NFT
    assert addr.same(transfer.source, NFT)
    assert addr.same(transfer.depositor, SENDER)
    assert transfer.amount == 1


def test_jetton_deposit_reports_the_jetton_wallet_as_source():
    body = (
        begin_cell()
        .store_uint(OP_JETTON_TRANSFER_NOTIFICATION, 32)
        .store_uint(0, 64)
        .store_coins(42)
        .store_address(SENDER)
        .store_bit_int(0)
        .end_cell()
    )
    transfer = parse_transaction(transaction(body, src=JWALLET, value=50_000_000), ESCROW)
    assert transfer is not None
    assert transfer.kind is TransferKind.JETTON
    assert addr.same(transfer.source, JWALLET)
    assert transfer.amount == 42


def test_bounced_messages_are_not_deposits():
    assert parse_transaction(transaction(comment_body("hi"), bounced=True), ESCROW) is None


def test_messages_to_another_account_are_ignored():
    other = Address("0:" + "f" * 64)
    assert parse_transaction(transaction(comment_body("hi"), dest=other), ESCROW) is None


def test_our_own_outgoing_externals_are_ignored():
    assert parse_transaction(transaction(comment_body("hi"), external=True), ESCROW) is None


def test_zero_value_messages_without_a_payload_are_ignored():
    assert parse_transaction(transaction(comment_body("hi"), value=0), ESCROW) is None


def test_transfer_key_combines_lt_and_hash():
    transfer = parse_transaction(transaction(comment_body("x"), lt=77), ESCROW)
    assert transfer is not None
    assert transfer.key.startswith("77:")
