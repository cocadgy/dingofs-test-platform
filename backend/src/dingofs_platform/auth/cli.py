import argparse, getpass
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from dingofs_platform.settings import Settings
from dingofs_platform.auth.service import create_user


def main():
    parser = argparse.ArgumentParser(
        description="Create a local platform account; run migrations first."
    )
    parser.add_argument("command", choices=["create-admin", "create-member"])
    args = parser.parse_args()
    username = input("Username: ").strip()
    email = input("Email (required): ").strip()
    password = getpass.getpass("Password (at least 6 characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    engine = create_engine(Settings().database_url)
    with Session(engine) as db:
        create_user(
            db,
            username,
            password,
            "admin" if args.command == "create-admin" else "member",
            email=email,
        )
    print("Account created:", username)


if __name__ == "__main__":
    main()
