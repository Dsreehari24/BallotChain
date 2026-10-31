from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Idempotently creates exactly 5 generic candidate accounts "
        "(candidate1@ballotchain.com through candidate5@ballotchain.com) "
        "with hashed passwords as normal authenticated accounts."
    )

    CANDIDATE_ACCOUNTS = [
        {"username": "candidate1", "email": "candidate1@ballotchain.com", "password": "c1@ballotchain", "first_name": "Candidate", "last_name": "1"},
        {"username": "candidate2", "email": "candidate2@ballotchain.com", "password": "c2@ballotchain", "first_name": "Candidate", "last_name": "2"},
        {"username": "candidate3", "email": "candidate3@ballotchain.com", "password": "c3@ballotchain", "first_name": "Candidate", "last_name": "3"},
        {"username": "candidate4", "email": "candidate4@ballotchain.com", "password": "c4@ballotchain", "first_name": "Candidate", "last_name": "4"},
        {"username": "candidate5", "email": "candidate5@ballotchain.com", "password": "c5@ballotchain", "first_name": "Candidate", "last_name": "5"},
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate candidate account creation without committing to database."
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.stdout.write("[*] Candidate Account Initialization: Checking 5 candidate accounts...")

        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            for acc in self.CANDIDATE_ACCOUNTS:
                uname = acc["username"]
                email = acc["email"]
                pwd = acc["password"]

                existing = User.objects.filter(username=uname).first() or User.objects.filter(email__iexact=email).first()
                if existing:
                    skipped_count += 1
                    self.stdout.write(f"    - Account {uname} ({email}) already exists (ID={existing.id}). Skipping.")
                    continue

                if not dry_run:
                    user = User(
                        username=uname,
                        email=email,
                        first_name=acc.get("first_name", ""),
                        last_name=acc.get("last_name", ""),
                        is_staff=False,
                        is_superuser=False,
                        is_active=True,
                    )
                    user.set_password(pwd)
                    user.save()
                created_count += 1
                self.stdout.write(f"    [+] Created candidate account: {uname} ({email})")

        action_word = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"[SUCCESS] Candidate accounts initialization complete. "
                f"{action_word}: {created_count}, Skipped: {skipped_count}."
            )
        )
