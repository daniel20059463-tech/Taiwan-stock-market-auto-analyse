from __future__ import annotations

import sector_data


def test_build_sector_map_from_shioaji_universe_maps_category_codes_to_sector_names() -> None:
    universe = {
        "2330": {"symbol": "2330", "sector": "24", "category": "24"},
        "1240": {"symbol": "1240", "sector": "33", "category": "33"},
        "9999": {"symbol": "9999", "sector": "CustomSector", "category": "CustomSector"},
    }

    sector_map = sector_data._build_sector_map_from_shioaji_universe(universe)

    assert sector_map["2330"] == "半導體"
    assert sector_map["1240"] == "農業科技業"
    assert sector_map["9999"] == "CustomSector"


def test_fetch_sector_map_augments_fresh_incomplete_cache_with_shioaji_universe(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "full_sector_map.json"
    cache_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(sector_data, "_cache_is_fresh", lambda path: True)
    monkeypatch.setattr(sector_data, "_load_cache", lambda path: {"2330": "半導體"})
    monkeypatch.setattr(
        sector_data,
        "_fetch_shioaji_universe_sector_map",
        lambda: {"1240": "農業科技業", "6488": "半導體"},
    )

    saved: dict[str, str] = {}

    def _save_cache(path: str, data: dict[str, str]) -> None:
        saved.clear()
        saved.update(data)

    monkeypatch.setattr(sector_data, "_save_cache", _save_cache)

    sector_map = sector_data.fetch_sector_map(str(cache_path))

    assert sector_map["2330"] == "半導體"
    assert sector_map["1240"] == "農業科技業"
    assert sector_map["6488"] == "半導體"
    assert saved == sector_map


def test_load_sinopac_credentials_reads_dotenv_before_env_lookup(monkeypatch, tmp_path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "SINOPAC_API_KEY=test-key\nSINOPAC_SECRET_KEY=test-secret\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("SINOPAC_API_KEY", raising=False)
    monkeypatch.delenv("SINOPAC_SECRET_KEY", raising=False)

    api_key, secret_key = sector_data._load_sinopac_credentials(str(dotenv_path))

    assert api_key == "test-key"
    assert secret_key == "test-secret"
