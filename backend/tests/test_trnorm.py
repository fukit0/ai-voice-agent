import pytest

from backend.app.trnorm import changes, normalize, number_to_words


@pytest.mark.parametrize("n,expected", [
    (0, "sıfır"), (1, "bir"), (10, "on"), (21, "yirmi bir"), (100, "yüz"), (101, "yüz bir"),
    (200, "iki yüz"), (1000, "bin"), (1001, "bin bir"), (2000, "iki bin"), (1990, "bin dokuz yüz doksan"),
    (2026, "iki bin yirmi altı"), (100000, "yüz bin"), (1_000_000, "bir milyon"),
    (1_250_000, "bir milyon iki yüz elli bin"), (2_000_000_000, "iki milyar"), (-5, "eksi beş"),
    (1_000_001_000, "bir milyar bin"),
])
def test_number_to_words(n, expected):
    assert number_to_words(n) == expected


def test_acceptance_sentence_from_feature_list():
    # norm-007 doğrulama maddesi: '1.250.000 TL', '22.10.2026', '0532 123 45 67'
    out = normalize("Fiyat 1.250.000 TL, ilan 22.10.2026 tarihinde yayınlandı, 0532 123 45 67 numarasını arayın.")
    assert out == ("Fiyat bir milyon iki yüz elli bin lira, ilan yirmi iki Ekim iki bin yirmi altı tarihinde "
                   "yayınlandı, sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi numarasını arayın.")


@pytest.mark.parametrize("text,expected", [
    ("12,50 TL", "on iki lira elli kuruş"),
    ("12,5 TL", "on iki lira elli kuruş"),
    ("750 TL", "yedi yüz elli lira"),
    ("1.250.000₺", "bir milyon iki yüz elli bin lira"),
    ("₺2.500", "iki bin beş yüz lira"),
    ("$50", "elli dolar"),
    ("€1.200,50", "bin iki yüz avro elli sent"),
    ("2.500.000 USD", "iki milyon beş yüz bin dolar"),
    ("1,5 milyon TL", "bir virgül beş milyon lira"),
    ("500 bin TL", "beş yüz bin lira"),
    ("750 TL'ye", "yedi yüz elli liraya"),  # ek, okunan sözcüğe uydurulur
    ("750 TL'den", "yedi yüz elli liradan"),
    ("750 TL'nin", "yedi yüz elli liranın"),
    ("€5'ya", "beş avroya"),
])
def test_money(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("0532 123 45 67", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("05321234567", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("532 123 45 67", "beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("+90 532 123 45 67", "artı doksan, beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"),
    ("(0212) 555 12 34", "sıfır iki yüz on iki, beş yüz elli beş, on iki, otuz dört"),
    ("0532 105 05 07", "sıfır beş yüz otuz iki, yüz beş, sıfır beş, sıfır yedi"),  # grup içi baştaki sıfır korunur
    ("0532-123-45-67'yi", "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yediyi"),
])
def test_phone(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("22.10.2026", "yirmi iki Ekim iki bin yirmi altı"),
    ("01/01/2027", "bir Ocak iki bin yirmi yedi"),
    ("22.10.2026'da", "yirmi iki Ekim iki bin yirmi altıda"),
    ("32.13.2026", "32.13.2026"),  # geçersiz tarih: dokunma
    ("14:30", "on dört otuz"),
    ("09:05", "dokuz sıfır beş"),
    ("18:00", "on sekiz"),
    ("saat 8:15'te", "saat sekiz on beşte"),
])
def test_date_time(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("%25", "yüzde yirmi beş"),
    ("25%", "yüzde yirmi beş"),
    ("%12,5", "yüzde on iki virgül beş"),
    ("3+1", "üç artı bir"),
    ("2+1 daire", "iki artı bir daire"),
    ("120 m²", "yüz yirmi metrekare"),
    ("85,5 m2", "seksen beş virgül beş metrekare"),
    ("120 m²'lik", "yüz yirmi metrekarelik"),
    ("12,5", "on iki virgül beş"),
    ("3,05", "üç virgül sıfır beş"),
    ("2026'da", "iki bin yirmi altıda"),
    ("5'te", "beşte"),
    ("007", "sıfır sıfır yedi"),
    ("1234567", "bir iki üç dört beş altı yedi"),
    ("iPhone 15", "iPhone on beş"),
])
def test_other_numbers(text, expected):
    assert normalize(text) == expected


def test_untouched_text_and_identifiers():
    assert normalize("Merhaba, ben Ayşe. Size kısa bir anket yapabilir miyim?") == (
        "Merhaba, ben Ayşe. Size kısa bir anket yapabilir miyim?")
    assert normalize("A4 kağıt ve B12 vitamini") == "A4 kağıt ve B12 vitamini"
    assert normalize("") == ""


def test_is_idempotent():
    once = normalize("Fiyat 1.250.000 TL, 3+1, %25, 14:30, 0532 123 45 67, 22.10.2026")
    assert normalize(once) == once


def test_changes_lists_conversions_for_preview():
    ch = changes("Fiyat 1.250.000 TL, 3+1 daire.")
    assert ch == [{"from": "1.250.000 TL", "to": "bir milyon iki yüz elli bin lira"},
                  {"from": "3+1", "to": "üç artı bir"}]


@pytest.mark.parametrize("text,expected", [
    ("1. kat", "birinci kat"),
    ("2. el araba", "ikinci el araba"),
    ("21. yüzyıl", "yirmi birinci yüzyıl"),
    ("Fiyat 5. Sonra", "Fiyat beş. Sonra"),  # arkasından büyük harf: cümle sonu, sıra sayısı değil
    ("2026-10-23", "yirmi üç Ekim iki bin yirmi altı"),
    ("100.000 km", "yüz bin kilometre"),
    ("75 kg", "yetmiş beş kilogram"),
    ("-5 derece", "eksi beş derece"),
    ("10-20 bin TL", "on-yirmi bin lira"),
    ("Saat 14.30'da", "Saat on dört otuzda"),
    ("1e6", "1e6"),
    ("%100", "yüzde yüz"),
    ("1.000 m²", "bin metrekare"),
])
def test_ordinals_units_iso_dates_and_edge_cases(text, expected):
    assert normalize(text) == expected


def test_marka_alan_adi_okunur():
    assert normalize("Sahibinden.com adına arıyorum.") == "sahibinden nokta kom adına arıyorum."
    assert normalize("Sahibinden.com'un verdiği yetki") == "sahibinden nokta komun verdiği yetki"
    assert "." not in normalize("sahibinden.com'a hoş geldiniz").replace("geldiniz", "")
