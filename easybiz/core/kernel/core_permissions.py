CORE_PERMISSIONS: list[tuple[str, str]] = [
    ("core.module.read", "See modules and their status"),
    ("core.module.manage", "Enable, disable, and remove modules"),
    ("core.role.read", "See roles"),
    ("core.role.manage", "Create and edit roles"),
    ("core.user.read", "See users and their roles"),
    ("core.user.manage", "Add, remove, and assign roles to users"),
    ("core.audit.read", "Read the tenant audit log"),
]
