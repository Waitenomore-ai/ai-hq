import argparse
import getpass

from argon2 import PasswordHasher


def _hash_admin_password() -> None:
    password = getpass.getpass("New AI HQ admin password: ")
    confirmation = getpass.getpass("Confirm AI HQ admin password: ")
    if password != confirmation:
        raise SystemExit("AI HQ admin passwords do not match")
    if len(password) < 12:
        raise SystemExit("AI HQ admin password must be at least 12 characters")
    print(PasswordHasher().hash(password))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-hq")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "hash-admin-password",
        help="prompt securely and print an Argon2 hash for AI_HQ_ADMIN_PASSWORD_HASH",
    )
    args = parser.parse_args(argv)
    if args.command == "hash-admin-password":
        _hash_admin_password()
