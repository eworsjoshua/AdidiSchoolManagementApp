import os

from django.core.management.base import BaseCommand

from administrator.models import User


class Command(BaseCommand):
    help = "Create the first admin from environment variables, if none exists."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME")
        email = os.environ.get("ADMIN_EMAIL")
        password = os.environ.get("ADMIN_PASSWORD")
        reset = os.environ.get("ADMIN_RESET_PASSWORD", "False") == "True"

        if not (username and email and password):
            self.stdout.write("ADMIN_* variables not set. Skipping.")
            return

        existing = User.objects.filter(username=username).first()
        if existing and reset:
            existing.set_password(password)
            existing.role = "admin"
            existing.is_active = True
            existing.save()
            self.stdout.write(f"Reset password for '{username}'.")
            return

        if User.objects.filter(role="admin").exists():
            self.stdout.write("An admin already exists. Skipping.")
            return

        User.objects.create_superuser(username=username, email=email, password=password, role="admin")
        self.stdout.write(f"Created admin '{username}'.")