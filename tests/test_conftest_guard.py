from tests.conftest import same_database


def test_same_database_ignores_credentials_and_driver_options() -> None:
    a = "postgresql+asyncpg://u:p@db.example:5432/newsroom?ssl=require"
    assert same_database(a, "postgresql+asyncpg://other:x@db.example/newsroom")
    assert not same_database(a, "postgresql+asyncpg://u:p@db.example:5432/newsroom_test")
    assert not same_database(a, "postgresql+asyncpg://u:p@localhost:5432/newsroom")
