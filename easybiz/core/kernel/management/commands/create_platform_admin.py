from django.core.management.base import BaseCommand, CommandError

from easybiz.core.users.models import User


class Command(BaseCommand):
    """Create a platform admin, or promote an existing user. Idempotent."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--password")
        parser.add_argument("--name", default="")

    def handle(self, *args, **options) -> None:
        email = options["email"].lower()
        password = options["password"]
        user = User.objects.filter(email=email).first()
        if user is None:
            if not password or len(password) < 10:
                raise CommandError(
                    "a new platform admin needs a password of at least 10 characters"
                )
            User.objects.create_user(
                email=email, password=password, name=options["name"], is_platform_admin=True
            )
            self.stdout.write(f"created platform admin {email}")
            return
        if password:
            user.set_password(password)
        user.is_platform_admin = True
        user.save(
            update_fields=["is_platform_admin", "password"] if password else ["is_platform_admin"]
        )
        self.stdout.write(f"promoted {email} to platform admin")
