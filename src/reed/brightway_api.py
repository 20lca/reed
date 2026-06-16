import bw2data as bd

from .utils import CONFIG, Config


def import_bonsai(path_to_tidy_files):
    from .import_db import import_bonsai as import_bonsai_impl

    return import_bonsai_impl(path_to_tidy_files)


def import_reed_db(reed_path=None):
    from .import_db import import_reed_db as import_reed_db_impl

    return import_reed_db_impl(reed_path=reed_path)


def required_brightway_databases(settings: Config = CONFIG) -> set[str]:
    """Return database names required before REED calculations can run."""
    return {
        "reed",
        settings.BONSAI_NAME,
        f"{settings.BONSAI_NAME} biosphere",
    }


def missing_brightway_databases(settings: Config = CONFIG) -> list[str]:
    """Return required Brightway databases missing from the configured project."""
    bd.projects.set_current(settings.PROJECT_NAME)
    existing = set(bd.databases)
    return sorted(required_brightway_databases(settings) - existing)


def ensure_brightway_databases(settings: Config = CONFIG) -> None:
    """Ensure Brightway dependencies exist and rebuild the foreground REED DB."""
    bd.projects.set_current(settings.PROJECT_NAME)
    existing = set(bd.databases)
    required_bonsai_databases = {
        settings.BONSAI_NAME,
        f"{settings.BONSAI_NAME} biosphere",
    }
    missing_bonsai_databases = sorted(required_bonsai_databases - existing)
    missing = sorted(required_brightway_databases(settings) - existing)

    bonsai_path = settings.BONSAI_PATH
    if missing_bonsai_databases and not bonsai_path.exists():
        raise RuntimeError(
            "Brightway startup import required but BONSAI_PATH does not exist: "
            f"{bonsai_path}. Missing databases: {', '.join(missing)}"
        )

    try:
        if missing_bonsai_databases:
            import_bonsai(bonsai_path)
        if "reed" in bd.databases:
            bd.Database("reed").delete(warn=False)
        import_reed_db(reed_path=settings.REED_PATH)
    except Exception as exc:
        raise RuntimeError(
            "Brightway startup import failed. "
            f"Missing databases before import: {', '.join(missing)}. "
            f"BONSAI_PATH: {bonsai_path}. Error: {exc}"
        ) from exc

    still_missing = missing_brightway_databases(settings)
    if still_missing:
        raise RuntimeError(
            "Brightway startup import completed but required databases are still "
            f"missing: {', '.join(still_missing)}"
        )

