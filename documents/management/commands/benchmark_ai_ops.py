import json
import time

from django.core.management.base import BaseCommand

from documents.jobs import _refresh_duplicate_flags
from search.search_service import search_documents
from documents.models import ProcessingMetric


class Command(BaseCommand):
    help = 'Run lightweight benchmarks for search and duplicate refresh.'

    def add_arguments(self, parser):
        parser.add_argument('--query', default='qa', help='Search query for benchmark.')
        parser.add_argument('--output', default='', help='Optional output json file path.')

    def handle(self, *args, **options):
        query = options['query']
        t0 = time.perf_counter()
        list(search_documents(query)[:50])
        search_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        dup_msg = _refresh_duplicate_flags()
        dup_ms = (time.perf_counter() - t1) * 1000

        report = {
            'search_ms': round(search_ms, 2),
            'duplicate_refresh_ms': round(dup_ms, 2),
            'duplicate_refresh_msg': dup_msg,
        }
        ProcessingMetric.objects.create(metric_name='benchmark_search_ms', metric_value=search_ms, unit='ms', meta={'query': query})
        ProcessingMetric.objects.create(metric_name='benchmark_duplicate_refresh_ms', metric_value=dup_ms, unit='ms', meta={})

        out = options.get('output') or ''
        if out:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
        self.stdout.write(self.style.SUCCESS(json.dumps(report)))
