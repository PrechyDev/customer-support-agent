"""Who may do what in the support console (docs/CONSOLE_API.md "Roles"). Pure functions, so they're easy to test.

superadmin (the owner) > admin > support. Admins manage support staff only; only the superadmin manages admins;
nobody can change or disable the superadmin.
"""

INVITABLE = {"superadmin": ("admin", "support"), "admin": ("support",), "support": ()}


def is_admin(role: str) -> bool:
    return role in ("superadmin", "admin")


def permissions(role: str) -> dict[str, bool]:
    return {"manage_team": is_admin(role), "manage_admins": role == "superadmin",
            "assign_cases": is_admin(role), "reopen_cases": is_admin(role)}


def can_invite(actor_role: str, new_role: str) -> bool:
    return new_role in INVITABLE.get(actor_role, ())


def can_manage(actor_role: str, target_role: str) -> bool:
    """Resend, reset link, disable, re-enable."""
    return target_role != "superadmin" and can_invite(actor_role, target_role)


def can_change_role(actor_role: str, target_role: str, new_role: str) -> bool:
    return actor_role == "superadmin" and target_role != "superadmin" and new_role in ("admin", "support")


def can_resolve(actor_role: str, actor_id: str, owner_id: str | None) -> bool:
    return is_admin(actor_role) or (owner_id is not None and owner_id == actor_id)
