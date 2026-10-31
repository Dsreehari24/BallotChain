from django.core.management.base import BaseCommand
from django.utils import timezone
from home.methods_module import process_scheduled_election_transitions


class Command(BaseCommand):
    help = 'Executes idempotent automated lifecycle transitions for scheduled elections (start and end).'

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(f"[{now.isoformat()}] Processing scheduled election transitions...")
        result = process_scheduled_election_transitions(now=now)
        
        started = result.get('started', [])
        ended = result.get('ended', [])
        mined = result.get('mined_batches', [])

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed. Started: {len(started)} (IDs: {started}), "
                f"Ended: {len(ended)} (IDs: {ended}), "
                f"Mined batches: {len(mined)} (IDs: {mined})"
            )
        )
