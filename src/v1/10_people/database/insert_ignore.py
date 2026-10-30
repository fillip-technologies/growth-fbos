from sqlalchemy import Insert, insert


def insert_ignore(model: type) -> Insert:
    """
    An INSERT that skips rows whose primary or unique key is already taken, instead of
    failing: `INSERT IGNORE` on MySQL/MariaDB, `INSERT OR IGNORE` on SQLite (the tests).
    Concurrent writers creating the same row (two service instances seeding, two first
    requests in a new organization) then can't trip over each other.
    """
    return (
        insert(model)
        .prefix_with("IGNORE", dialect="mysql")
        .prefix_with("IGNORE", dialect="mariadb")
        .prefix_with("OR IGNORE", dialect="sqlite")
    )
