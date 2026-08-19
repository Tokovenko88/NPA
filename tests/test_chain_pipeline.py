from datetime import date

from scripts.chain_pipeline import get_npa_date, scan_input_folder


def test_get_npa_date_uses_canonical_iso_parser():
    assert get_npa_date({'date_signed': '2026-08-19'}) == date(2026, 8, 19)


def test_get_npa_date_accepts_external_npa_format():
    assert get_npa_date({'date_signed': '19.08.2026'}) == date(2026, 8, 19)


def test_get_npa_date_falls_back_to_next_date_field():
    assert get_npa_date({
        'date_signed': 'not-a-date',
        'date_pub': '2026-08-20',
    }) == date(2026, 8, 20)


def test_scan_input_folder_sorts_amendments_chronologically(tmp_path):
    files = {
        'target_npa.json': {'npa_number': '1', 'date_signed': '2026-01-01'},
        '300-ЗС.json': {'npa_number': '300', 'date_signed': '2026-03-01'},
        '200-ЗС.json': {'npa_number': '200', 'date_signed': '2026-02-01'},
        '100-ЗС.json': {'npa_number': '100', 'date_signed': '2026-04-01'},
    }
    for filename, data in files.items():
        (tmp_path / filename).write_text(
            __import__('json').dumps(data), encoding='utf-8'
        )

    target, amendments = scan_input_folder(str(tmp_path))

    assert target['filename'] == 'target_npa.json'
    assert [item['filename'] for item in amendments] == [
        '200-ЗС.json',
        '300-ЗС.json',
        '100-ЗС.json',
    ]
