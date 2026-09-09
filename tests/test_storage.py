from tests.conftest import JETTON_WALLET, NFT_ITEM

from guarantor.models import Asset, AssetKind, Deal, DealStatus, Side, SideRole


def make_deal(code: str, status: DealStatus = DealStatus.AWAITING_DEPOSITS) -> Deal:
    return Deal(
        code=code,
        status=status,
        a=Side(role=SideRole.A, asset=Asset(kind=AssetKind.TON, amount=10**9), user_id=1),
        b=Side(role=SideRole.B, asset=Asset(kind=AssetKind.NFT, nft_address=NFT_ITEM), user_id=2),
        expires_at=1_800_000_000,
    )


async def test_deal_round_trip(storage):
    original = make_deal("AAAAAAAA")
    await storage.put_deal(original)
    loaded = await storage.get_deal("AAAAAAAA")
    assert loaded is not None
    assert loaded.to_dict() == original.to_dict()


async def test_put_deal_is_an_upsert(storage):
    deal = make_deal("BBBBBBBB")
    await storage.put_deal(deal)
    deal.status = DealStatus.COMPLETED
    await storage.put_deal(deal)
    loaded = await storage.get_deal("BBBBBBBB")
    assert loaded is not None and loaded.status is DealStatus.COMPLETED


async def test_lookup_by_nft_only_finds_deals_still_awaiting_it(storage):
    deal = make_deal("CCCCCCCC")
    await storage.put_deal(deal)
    assert (await storage.find_by_nft(NFT_ITEM)).code == "CCCCCCCC"

    deal.status = DealStatus.COMPLETED
    await storage.put_deal(deal)
    assert await storage.find_by_nft(NFT_ITEM) is None


async def test_lookup_by_jetton_wallet(storage):
    deal = make_deal("DDDDDDDD")
    deal.b.asset = Asset(
        kind=AssetKind.JETTON, amount=5, jetton_master="0:" + "2" * 64, jetton_wallet=JETTON_WALLET
    )
    await storage.put_deal(deal)
    found = await storage.find_by_jetton_wallet(JETTON_WALLET)
    assert [d.code for d in found] == ["DDDDDDDD"]


async def test_active_count_ignores_finished_deals(storage):
    await storage.put_deal(make_deal("EEEEEEEE"))
    await storage.put_deal(make_deal("FFFFFFFF", status=DealStatus.COMPLETED))
    assert await storage.count_active_for_user(1) == 1
    assert await storage.count_active_for_user(999) == 0


async def test_user_listing_covers_both_sides(storage):
    await storage.put_deal(make_deal("GGGGGGGG"))
    assert [d.code for d in await storage.list_deals_for_user(2)] == ["GGGGGGGG"]


async def test_transfer_keys_are_recorded_once(storage):
    assert await storage.mark_transfer_seen("1:abc") is True
    assert await storage.mark_transfer_seen("1:abc") is False


async def test_cursor_defaults_to_zero_and_persists(storage):
    assert await storage.get_cursor("escrow_lt") == 0
    await storage.set_cursor("escrow_lt", 12345)
    assert await storage.get_cursor("escrow_lt") == 12345


async def test_locale_preference_round_trip(storage):
    assert await storage.get_locale(7) is None
    await storage.set_locale(7, "ru")
    assert await storage.get_locale(7) == "ru"


async def test_stats_group_by_status(storage):
    await storage.put_deal(make_deal("HHHHHHHH"))
    await storage.put_deal(make_deal("IIIIIIII", status=DealStatus.COMPLETED))
    assert await storage.stats() == {"awaiting": 1, "completed": 1}
