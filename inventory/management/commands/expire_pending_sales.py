from django.core.management.base import BaseCommand

from sales.services import expire_stale_pending


class Command(BaseCommand):
    help = "Release stock held by unpaid sales older than N minutes. Run every few minutes from cron."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=15)

    def handle(self, *args, **opts):
        count = expire_stale_pending(opts["minutes"])
        self.stdout.write(f"Released {count} stale pending sale(s).")
