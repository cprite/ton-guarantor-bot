from guarantor.codes import ALPHABET, CODE_LENGTH, deposit_memo, new_deal_code, normalize_code, parse_memo


def test_codes_avoid_lookalike_characters():
    assert not set("IO01") & set(ALPHABET)


def test_new_code_shape():
    code = new_deal_code()
    assert len(code) == CODE_LENGTH
    assert all(char in ALPHABET for char in code)


def test_codes_are_not_repeated_trivially():
    assert len({new_deal_code() for _ in range(200)}) == 200


def test_normalize_forgives_how_people_retype_codes():
    code = new_deal_code()
    assert normalize_code(code.lower()) == code
    assert normalize_code(f" {code[:4]}-{code[4:]} ") == code


def test_normalize_rejects_wrong_shapes():
    assert normalize_code("SHORT") is None
    assert normalize_code("IIIIIIII") is None


def test_memo_round_trip():
    code = new_deal_code()
    assert parse_memo(deposit_memo(code, "A")) == (code, "A")
    assert parse_memo(deposit_memo(code, "b")) == (code, "B")


def test_memo_rejects_unrelated_comments():
    assert parse_memo("thanks!") is None
    assert parse_memo("G-SHORT-A") is None
