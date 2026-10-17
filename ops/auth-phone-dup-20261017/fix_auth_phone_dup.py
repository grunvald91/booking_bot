"""Fix phone login when several users share one phone number.

Live auth.py used scalar_one_or_none() on User.phone, which raises
"Multiple rows were found" for duplicates and broke both sending and
verifying the code. Both paths now use one deterministic lookup: a row
with a real Telegram id first (the code is delivered there), then the
oldest. No database rows are changed.

Usage: python fix_auth_phone_dup.py <auth.py> [expected_sha256]
"""
import hashlib
import sys

path = sys.argv[1]
expected = sys.argv[2] if len(sys.argv) > 2 else None
src = open(path, encoding="utf-8").read()
if expected and hashlib.sha256(src.encode()).hexdigest() != expected:
    sys.exit("ABORT: auth.py differs from the reviewed version")


def replace_once(text, old, new):
    if text.count(old) != 1:
        sys.exit("ABORT: expected exactly one occurrence of: " + old.splitlines()[0])
    return text.replace(old, new)


src = replace_once(src, "from sqlalchemy import select\n", "from sqlalchemy import case, select\n")
src = replace_once(
    src,
    "# ---------- POST /auth/phone ----------\n",
    '''async def _user_by_phone(db: AsyncSession, phone: str) -> Optional[User]:
    """Several users may share a phone; prefer a real Telegram account, then the oldest."""
    result = await db.execute(
        select(User)
        .where(User.phone == phone)
        .order_by(case((User.telegram_id > 0, 0), else_=1), User.id)
        .limit(1)
    )
    return result.scalars().first()


# ---------- POST /auth/phone ----------
''',
)
src = replace_once(
    src,
    "        result = await db.execute(select(User).where(User.phone == phone))\n"
    "        user = result.scalar_one_or_none()\n",
    "        user = await _user_by_phone(db, phone)\n",
)
src = replace_once(
    src,
    "    result = await db.execute(select(User).where(User.phone == phone))\n"
    "    user = result.scalar_one_or_none()\n",
    "    user = await _user_by_phone(db, phone)\n",
)
open(path, "w", encoding="utf-8").write(src)
print("patched", hashlib.sha256(src.encode()).hexdigest())
