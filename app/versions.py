"""简单语义版本（major.minor.patch）比较工具。"""

from __future__ import annotations


def parse_version(version: str) -> tuple[int, int, int]:
    """把 ``"1.2.3"`` 解析为三元组；非法格式抛出 ``ValueError``。"""
    if not isinstance(version, str):
        raise ValueError(f"版本号必须是字符串: {version!r}")
    parts = version.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"版本号必须形如 major.minor.patch: {version!r}")
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"版本号包含非数字段: {version!r}") from exc
    if major < 0 or minor < 0 or patch < 0:
        raise ValueError(f"版本号段不能为负: {version!r}")
    return major, minor, patch


def version_gap(source: str, target: str) -> int:
    """目标版本与源版本在补丁序号上的跨度（target - source）。

    约定大版本/小版本必须一致（固件只在同一 major.minor 线上发布补丁），
    此时跨度为补丁号之差；跨线时返回一个足够大的哨兵值，确保被判定为
    跨度过大，而不是默默放行。
    """
    s_major, s_minor, s_patch = parse_version(source)
    t_major, t_minor, t_patch = parse_version(target)
    if (s_major, s_minor) != (t_major, t_minor):
        # 跨大版本/小版本：不允许直接升级补丁
        return 10**6 + abs(t_patch - s_patch)
    return t_patch - s_patch
