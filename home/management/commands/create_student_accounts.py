import sys
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Idempotently creates exactly 1,000 student User accounts for testing "
        "(2411CS070001 through 2411CS071000) with hashed passwords and university email mapping."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            type=int,
            default=1,
            help="Starting sequence number (default: 1 for 2411CS070001)"
        )
        parser.add_argument(
            '--end',
            type=int,
            default=1000,
            help="Ending sequence number (default: 1000 for 2411CS071000)"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate account creation without writing to database"
        )

    def handle(self, *args, **options):
        start_idx = options['start']
        end_idx = options['end']
        dry_run = options['dry_run']

        if start_idx < 1 or end_idx < start_idx:
            self.stderr.write(self.style.ERROR(f"Invalid range: {start_idx} to {end_idx}"))
            return

        expected_count = end_idx - start_idx + 1
        self.stdout.write(
            f"[*] Account Generation: Sequence {start_idx} to {end_idx} ({expected_count} accounts)"
        )

        created_count = 0
        skipped_count = 0
        conflict_count = 0

        # Pre-fetch existing users in a single query
        existing_users_dict = {
            u.username: u for u in User.objects.all()
        }
        existing_emails_dict = {
            u.email.lower(): u for u in existing_users_dict.values() if u.email
        }

        self.stdout.write(f"[*] Baseline existing users in database: {len(existing_users_dict)}")

        users_to_create = []

        for i in range(start_idx, end_idx + 1):
            account_id = f"2411CS07{i:04d}"
            email = f"2411cs07{i:04d}@mallareddyuniversity.ac.in"
            password = account_id

            existing_user = existing_users_dict.get(account_id)
            existing_by_email = existing_emails_dict.get(email.lower())

            if existing_user and existing_by_email and existing_user.id == existing_by_email.id:
                skipped_count += 1
                continue
            elif existing_user or existing_by_email:
                conflict_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[!] Conflict for {account_id} / {email}: "
                        f"user_id={getattr(existing_user, 'id', None)}, email_user_id={getattr(existing_by_email, 'id', None)}"
                    )
                )
                continue

            user = User(
                username=account_id,
                email=email,
                first_name="",
                last_name="",
                is_staff=False,
                is_superuser=False,
                is_active=True,
            )
            if not dry_run:
                user.set_password(password)
            users_to_create.append(user)
            created_count += 1

            if not dry_run and created_count % 200 == 0:
                self.stdout.write(f"[*] Prepared {created_count}/{expected_count} accounts with password hash...")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[DRY-RUN] Verification complete:\n"
                    f"    - Would create: {len(users_to_create)}\n"
                    f"    - Would skip (already exists): {skipped_count}\n"
                    f"    - Conflicts: {conflict_count}\n"
                    f"    - Sample Account: ID={account_id}, Email={email}, Password={password}"
                )
            )
            return

        # Perform atomic batch creation
        if users_to_create:
            self.stdout.write(f"[*] Inserting {len(users_to_create)} users into database...")
            with transaction.atomic():
                User.objects.bulk_create(users_to_create, batch_size=250)

        total_users_now = User.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"[SUCCESS] Account generation completed successfully.\n"
                f"    - Created: {created_count}\n"
                f"    - Skipped (already existed): {skipped_count}\n"
                f"    - Conflicts: {conflict_count}\n"
                f"    - Total Users in DB: {total_users_now}"
            )
        )
