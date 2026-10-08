"""骨架冒烟测试，确认包可导入。"""


def test_imports() -> None:
    import app.api  # noqa: F401
    import app.compatibility  # noqa: F401
    import app.errors  # noqa: F401
    import app.models  # noqa: F401
    import app.rollout  # noqa: F401
    import app.store  # noqa: F401
