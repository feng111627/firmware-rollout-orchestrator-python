"""兼容判定与发布准入测试。"""
from __future__ import annotations

import pytest

from app.compatibility import check_admission, is_version_compatible, parse_version
from app.errors import (
    ModelNotSupportedError,
    TargetVersionNotFoundError,
    VersionGapError,
)
from app.models import Device, Firmware


def make_device(model: str = "MX-100", version: str = "1.2.0") -> Device:
    return Device(device_id="d1", model=model, version=version)


def make_firmware(min_from: str | None = "1.0.0") -> Firmware:
    return Firmware(
        version="2.0.0",
        supported_models=frozenset({"MX-100", "MX-200"}),
        min_upgrade_from=min_from,
    )


def test_parse_version_basic_and_suffix() -> None:
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("2.0.0-rc1") == (2, 0, 0)
    assert parse_version("3") == (3,)


def test_parse_version_bad() -> None:
    with pytest.raises(ValueError):
        parse_version("not-a-version")


def test_version_compatible_within_gap() -> None:
    fw = make_firmware("1.0.0")
    assert is_version_compatible("1.0.0", fw)
    assert is_version_compatible("1.5.2", fw)
    assert not is_version_compatible("0.9.9", fw)


def test_version_compatible_no_constraint() -> None:
    assert is_version_compatible("0.1.0", make_firmware(None))


def test_admission_passes() -> None:
    assert check_admission(make_device(), make_firmware()) is None


def test_admission_target_not_found() -> None:
    with pytest.raises(TargetVersionNotFoundError) as exc:
        check_admission(make_device(), None)
    assert exc.value.code == "target_version_not_found"


def test_admission_model_not_supported() -> None:
    with pytest.raises(ModelNotSupportedError) as exc:
        check_admission(make_device(model="MX-999"), make_firmware())
    assert exc.value.code == "model_not_supported"


def test_admission_version_gap() -> None:
    with pytest.raises(VersionGapError) as exc:
        check_admission(make_device(version="0.8.0"), make_firmware())
    assert exc.value.code == "version_gap_too_large"


def test_admission_error_types_are_distinguishable() -> None:
    """三种准入失败必须是不同的异常类型与 code。"""
    codes = {
        TargetVersionNotFoundError.code,
        ModelNotSupportedError.code,
        VersionGapError.code,
    }
    assert codes == {
        "target_version_not_found",
        "model_not_supported",
        "version_gap_too_large",
    }
