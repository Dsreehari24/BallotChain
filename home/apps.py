import os
import sys
import threading
import time
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class HomeConfig(AppConfig):
    name = 'home'

    def ready(self):
        # Prevent scheduler launch during test discovery or migrations
        is_testing = 'test' in sys.argv
        is_migration = any(arg in sys.argv for arg in ['migrate', 'makemigrations', 'createsuperuser', 'check'])
        if is_testing or is_migration:
            return

        should_run = (
            os.environ.get('RUN_MAIN') == 'true' or
            (any('runserver' in arg for arg in sys.argv) and not os.environ.get('RUN_MAIN')) or
            os.environ.get('ENABLE_LIFECYCLE_SCHEDULER') == 'true'
        )

        if should_run:
            def _scheduler_loop():
                time.sleep(1)  # Initial grace delay
                while True:
                    try:
                        from home.methods_module import process_scheduled_election_transitions
                        res = process_scheduled_election_transitions()
                        if res.get('started') or res.get('ended'):
                            logger.info(f"[LIFECYCLE SCHEDULER] Transitions executed: {res}")
                    except Exception as e:
                        logger.debug(f"[LIFECYCLE SCHEDULER] loop note: {e}")
                    time.sleep(5)

            thread = threading.Thread(
                target=_scheduler_loop,
                daemon=True,
                name="BallotChainLifecycleScheduler"
            )
            thread.start()
