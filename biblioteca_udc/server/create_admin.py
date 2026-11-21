"""Create the first administrator (or reset an admin password).

    python create_admin.py
"""
import getpass
import sys

import config
import security
from db import connect, init_db, now


def main() -> None:
    init_db()
    username = input("Admin username: ").strip()
    if not username:
        sys.exit("Username is required.")
    password = getpass.getpass("Password (min. 8 characters): ")
    if len(password) < 8:
        sys.exit("Password must have at least 8 characters.")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match.")
    conn = connect()
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        conn.execute("UPDATE users SET pw_hash=?, role='admin', disabled=0 WHERE id=?",
                     (security.hash_password(password), row["id"]))
        print(f"Updated existing user '{username}' (now admin).")
    else:
        conn.execute("INSERT INTO users(username,pw_hash,role,created_at) VALUES (?,?,?,?)",
                     (username, security.hash_password(password), "admin", now()))
        print(f"Admin '{username}' created.")
    conn.commit()
    conn.close()
    print(f"Data folder: {config.DATA_DIR}")


if __name__ == "__main__":
    main()
