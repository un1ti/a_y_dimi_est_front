"""Read-only data quality audit for persisted RAG extraction rows."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .rag_context_v21 import recover_dataset


def audit_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple, list[str]] = defaultdict(list)
    missing_dataset = missing_system = missing_value = recovered = 0
    rows = []
    for row in records:
        data = row.get('data') or {}
        evid = row.get('evidence') or []
        dataset, source = recover_dataset(data, evid)
        system = data.get('config_label') or data.get('rag_variant')
        metric = data.get('metric_name')
        value = data.get('metric_value')
        missing_dataset += dataset is None
        missing_system += not bool(system)
        missing_value += value is None
        recovered += source == 'recovered_from_verified_metric_quote'
        identifier = str(row.get('id') or row.get('record_id') or '')
        # Missing context means an apparent duplicate is *only* a candidate.
        key = (system, dataset, metric, str(value), data.get('data_split'),
               data.get('evaluation_protocol'))
        groups[key].append(identifier)
        rows.append({'record_id': identifier, 'dataset': dataset,
                     'dataset_source': source, 'system': system, 'metric': metric,
                     'value': value, 'ready_for_comparison': all((dataset, metric, value is not None,
                                                                  data.get('evaluation_protocol'), data.get('data_split')))})
    potential = [ids for ids in groups.values() if len(ids) > 1]
    return {'total': len(records), 'missing_dataset_after_recovery': missing_dataset,
            'recovered_dataset_count': recovered, 'missing_system': missing_system,
            'missing_metric_value': missing_value, 'potential_duplicate_groups': potential,
            'potential_extra_rows': sum(len(ids)-1 for ids in potential),
            'note': ('Possible duplicates are NOT deleted; incomplete records can be distinct '
                     'experiments. Recovery from a verified quote is provisional and does not '
                     'prove correct table-row/column association.'),
            'records': rows}
