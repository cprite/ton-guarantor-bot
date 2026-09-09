"""Translations must stay structurally identical, or a locale breaks at runtime."""

from __future__ import annotations

import re

from guarantor.bot.texts import EN, LOCALES, supported, t

PLACEHOLDER = re.compile(r"{(\w+)")


def placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER.findall(template))


def test_every_locale_defines_every_key():
    for name, table in LOCALES.items():
        assert set(table) == set(EN), f"{name} is missing or has extra keys"


def test_placeholders_match_across_locales():
    for name, table in LOCALES.items():
        for key, template in table.items():
            assert placeholders(template) == placeholders(EN[key]), f"{name}/{key}"


def test_every_template_formats_with_its_own_placeholders():
    for table in LOCALES.values():
        for template in table.values():
            kwargs = dict.fromkeys(placeholders(template), "x")
            template.format(**kwargs)  # raises if the template is malformed


def test_unknown_locales_fall_back_to_english():
    assert t("de", "btn_back") == EN["btn_back"]
    assert supported("de") == "en"
    assert supported("ru-RU") == "ru"


def test_missing_arguments_do_not_crash_a_message():
    assert "{" in t("en", "deal_row")  # rendered without arguments, left as-is
    assert t("en", "no_such_key") == "no_such_key"


def test_html_tags_are_balanced():
    for name, table in LOCALES.items():
        for key, template in table.items():
            for tag in ("b", "code", "pre", "a"):
                opens = len(re.findall(rf"<{tag}[ >]", template))
                closes = template.count(f"</{tag}>")
                assert opens == closes, f"{name}/{key}: <{tag}> is unbalanced"
