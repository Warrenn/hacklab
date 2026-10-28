from pathlib import Path

from hacklab.config import load_config


def test_defaults_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml", env={})
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8000
    assert cfg.data_dir == Path("data")
    assert cfg.fake_board is False
    assert cfg.api_key is None
    assert cfg.monthly_cap_usd > 0


def test_file_values_are_read(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text(
        '[app]\nport = 9000\ndata_dir = "/var/lib/hacklab"\nfake_board = true\n'
        '[ai]\nmodel = "claude-test"\nmonthly_cap_usd = 3\n'
    )
    cfg = load_config(f, env={})
    assert cfg.port == 9000
    assert cfg.data_dir == Path("/var/lib/hacklab")
    assert cfg.fake_board is True
    assert cfg.model == "claude-test"
    assert cfg.monthly_cap_usd == 3


def test_env_overrides_file(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text('[app]\nfake_board = false\ndata_dir = "data"\n')
    cfg = load_config(f, env={"FAKE_BOARD": "1", "HACKLAB_DATA_DIR": "/tmp/x"})
    assert cfg.fake_board is True
    assert cfg.data_dir == Path("/tmp/x")


def test_api_key_comes_from_env_only(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text('[ai]\napi_key = "sk-ant-should-be-ignored"\n')
    assert load_config(f, env={}).api_key is None
    assert load_config(f, env={"ANTHROPIC_API_KEY": "sk-ant-x"}).api_key == "sk-ant-x"
