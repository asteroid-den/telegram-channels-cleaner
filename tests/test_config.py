from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from channels_cleaner.cli import settings_error_message
from channels_cleaner.config import Settings, default_data_dir


def make_checkout(root: Path, name: str) -> None:
    (root / "src" / "channels_cleaner").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')


def test_checkout_keeps_local_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    make_checkout(tmp_path, "telegram-channels-cleaner")
    assert default_data_dir() == Path("data")


@pytest.mark.parametrize("other", ["data folder only", "other project"])
def test_data_folder_of_another_project_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    (tmp_path / "data").mkdir()

    if other == "other project":
        make_checkout(tmp_path, "someone-elses-app")

    assert default_data_dir() == tmp_path / "xdg" / "telegram-channels-cleaner"


def test_installed_app_uses_user_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_data_dir() == tmp_path / "xdg" / "telegram-channels-cleaner"


def test_data_from_before_the_rename_is_moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    legacy = tmp_path / "xdg" / "channels-cleaner"
    (legacy / "sessions").mkdir(parents=True)
    (legacy / "sessions" / "account.session").write_text("session")

    data_dir = default_data_dir()

    assert (data_dir / "sessions" / "account.session").read_text() == "session"
    assert not legacy.exists()


def test_existing_data_dir_wins_over_the_old_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "channels-cleaner").mkdir(parents=True)
    (tmp_path / "xdg" / "telegram-channels-cleaner").mkdir()

    default_data_dir()

    assert (tmp_path / "xdg" / "channels-cleaner").is_dir()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_data_dir_is_private(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "sessions").mkdir(parents=True, mode=0o755)
    data.chmod(0o755)  # left by an older version
    Settings(data_dir=data).ensure_dirs()

    for path in (data, data / "sessions"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    "values",
    [{"apply_delay_min": 5, "apply_delay_max": 1}, {"apply_delay_min": -1}, {"port": 0}, {"mock_channels": -3}],
)
def test_settings_that_make_no_sense_are_refused(tmp_path: Path, values: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, _env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_a_bad_setting_is_named_as_its_variable(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(data_dir=tmp_path, port=70000, _env_file=None)  # pyright: ignore[reportCallIssue]

    message = settings_error_message(caught.value)

    assert "CC_PORT" in message


def test_the_env_file_of_another_project_is_harmless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://x\nSECRET_KEY=abc\nCC_PORT=9001\n")

    settings = Settings(data_dir=tmp_path)

    # Only its CC_ keys count
    assert settings.port == 9001


def test_the_data_dir_is_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A relative one would be read against Kurigram's workdir by its downloads, not the cwd
    monkeypatch.chdir(tmp_path)

    settings = Settings(data_dir=Path("data"), _env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.data_dir == tmp_path / "data"
    assert settings.media_dir.is_absolute()
