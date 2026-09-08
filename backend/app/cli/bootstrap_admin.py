import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError

from app.core.database import async_session_factory
from app.modules.identity.bootstrap import (
    BootstrapConflictError,
    BootstrapStatus,
    bootstrap_first_admin,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the first administrator account exactly once."
    )
    parser.add_argument(
        "--username",
        default=os.getenv("BOOTSTRAP_ADMIN_USERNAME"),
        help="Administrator username (or BOOTSTRAP_ADMIN_USERNAME).",
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv("BOOTSTRAP_ADMIN_DISPLAY_NAME"),
        help="Display name (or BOOTSTRAP_ADMIN_DISPLAY_NAME).",
    )
    return parser


def _read_password() -> str:
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if password is not None:
        return password
    if not sys.stdin.isatty():
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD is required when input is not interactive")
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        raise RuntimeError("Password confirmation does not match")
    return password


async def _run(username: str, display_name: str, password: str) -> BootstrapStatus:
    async with async_session_factory() as session:
        result = await bootstrap_first_admin(
            session,
            username=username,
            display_name=display_name,
            password=password,
        )
    if result.status == BootstrapStatus.ALREADY_EXISTS and not result.is_active:
        raise BootstrapConflictError(
            "The administrator already exists but is disabled; bootstrap will not reactivate it"
        )
    return result.status


def main() -> int:
    args = _parser().parse_args()
    if not args.username:
        print(
            "Administrator username is required via --username or BOOTSTRAP_ADMIN_USERNAME.",
            file=sys.stderr,
        )
        return 2
    display_name = args.display_name or args.username
    try:
        password = _read_password()
        status = asyncio.run(_run(args.username, display_name, password))
    except ValidationError:
        print(
            "Administrator bootstrap failed: account fields do not meet validation requirements.",
            file=sys.stderr,
        )
        return 1
    except (BootstrapConflictError, RuntimeError) as exc:
        print(f"Administrator bootstrap failed: {exc}", file=sys.stderr)
        return 1
    if status == BootstrapStatus.CREATED:
        print(f"Administrator '{args.username}' created.")
    else:
        print(f"Administrator '{args.username}' already exists; no changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
