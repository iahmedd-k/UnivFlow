"""List or revoke private workspace access grants.

Run from backend/: python scripts/manage_private_access.py list
                 python scripts/manage_private_access.py revoke <clerk-user-id>
"""
import argparse
import json

from app.auth.access_gate import _key
from app.db.database import SessionLocal
from app.db.models import Setting


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Uniflow private beta access")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List accounts with access grants")
    revoke = commands.add_parser("revoke", help="Revoke one account's access")
    revoke.add_argument("user_id", help="Exact Clerk user ID")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.command == "list":
            rows = db.query(Setting).filter(Setting.key.like("private_access_grant_%")).order_by(Setting.updated_at.desc()).all()
            for row in rows:
                try:
                    grant = json.loads(row.value or "{}")
                except json.JSONDecodeError:
                    grant = {}
                print(f"{grant.get('email', 'unknown email')}  {grant.get('granted_at', 'unknown date')}  key={row.key}")
            if not rows:
                print("No access grants found.")
        else:
            deleted = db.query(Setting).filter(Setting.key == _key("grant", args.user_id)).delete(synchronize_session=False)
            db.query(Setting).filter(Setting.key == _key("otp", args.user_id)).delete(synchronize_session=False)
            db.commit()
            print("Access revoked." if deleted else "No grant existed for that account.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
