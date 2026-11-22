const configFields = {
  variant:'rag_variant', model:'generator_model', retrieval:'retrieval_method',
  embedding:'embedding_model', top_k:'top_k', chunk_size:'chunk_size',
  chunk_overlap:'chunk_overlap', chunk_unit:'chunk_unit'
};

const unique = values => [...new Set(values.filter(v => v != null && v !== ''))];

function configuration(data) {
  const config = {};
  for (const [key,field] of Object.entries(configFields)) {
    if (data[field] != null) config[key] = data[field];
  }
  if (!config.variant && data.config_label) config.variant = data.config_label;
  return config;
}

export function scientificResult({doc,job,records,quality}, title) {
  const findings = records.map(record => ({...record, config:configuration(record.data)}));
  const config = {}, evidence = {}, metrics = [];
  // Only fields shared without conflicting values can describe a whole publication.
  for (const [key,field] of Object.entries(configFields)) {
    const values = unique(findings.map(r => r.config[key]));
    if (values.length !== 1) continue;
    config[key] = values[0];
    const proof = findings.flatMap(r => r.evidence).find(e => e.field === field && e.verification === 'quote_matched');
    if (proof) evidence[key] = {page:proof.page, fragment:proof.quote};
  }
  for (const record of findings) {
    const d = record.data;
    const cfg = record.config;
    // A partial record cannot establish that another record used the same setup.
    const configId = JSON.stringify([doc.id,d.config_label,cfg,d.retriever_model,d.reranker_model,d.embedding_version,d.generator_version,d.chunking_method,d.index_type,d.vector_store,d.context_strategy,d.prompt_strategy]);
    const experimentId = JSON.stringify([configId,d.dataset_name,d.dataset_version,d.task_type,d.evaluation_protocol,d.data_split,d.baseline_name,d.sample_size]);
    const measurements = [
      ['metric_value', d.metric_name, d.metric_unit],
      ['latency_ms', 'Задержка', 'ms'], ['tokens_per_query', 'Токены на запрос', 'tokens/query']
    ];
    for (const [field,label,sourceUnit] of measurements) {
      if (d[field] == null || !label) continue;
      const proof = record.evidence.find(e => e.field === field && e.verification === 'quote_matched');
      const unit = sourceUnit === 'percent' ? '%' : sourceUnit || '';
      const name = field === 'metric_value' && d.metric_k != null && !label.includes('@') ? label + '@' + d.metric_k : label;
      metrics.push({
        id: record.id + ':' + field, record_id:record.id, name, raw:String(d[field]), unit,
        value:unit === '%' ? d[field]/100 : unit ? d[field] : null,
        normalized_unit: unit === '%' ? 'fraction' : unit,
        config_id: Object.keys(cfg).length ? configId : '', experiment_id: Object.keys(cfg).length ? experimentId : record.id,
        config:cfg, dataset:d.dataset_name, task:d.task_type, protocol:d.evaluation_protocol,
        data_split:d.data_split, metric_variant:d.metric_variant, metric_direction:d.metric_direction,
        metric_k:d.metric_k, aggregation:d.aggregation, origin:'unknown',
        page:proof?.page, fragment:proof?.quote
      });
    }
  }
  const tasks = unique(records.map(r=>r.data.task_type));
  const protocols = unique(records.map(r=>r.data.evaluation_protocol));
  return {
    title,kind:'PDF',datasets:unique(records.map(r=>r.data.dataset_name)),
    task:tasks.join(', '),protocol:protocols.join(' · '),config,evidence,metrics,
    scientific:{version:'2.5',publication_id:doc.id,job_id:job.id,mode:job.llm_mode,
      model:job.llm_model,records,quality}
  };
}
