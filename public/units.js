const plurals = new Intl.PluralRules('ru');
const percent = new Intl.NumberFormat('ru', { style: 'percent', maximumFractionDigits: 3 });
const forms = {
  tokens: ['токен', 'токена', 'токенов'],
  characters: ['символ', 'символа', 'символов'],
  words: ['слово', 'слова', 'слов'],
  bytes: ['байт', 'байта', 'байт'],
  chunks: ['фрагмент', 'фрагмента', 'фрагментов'],
  documents: ['документ', 'документа', 'документов'],
  results: ['результат', 'результата', 'результатов']
};
const aliases = { token:'tokens', char:'characters', chars:'characters', character:'characters', word:'words', byte:'bytes', chunk:'chunks', document:'documents' };

function quantity(value, unit) {
  const key = String(unit || '').trim().toLowerCase();
  const labels = Object.hasOwn(forms, key) ? forms[key] : forms[aliases[key]];
  if (!labels) return unit ? value + ' ' + unit : value + ' (единица не указана)';
  const form = plurals.select(Number(String(value).replace(',', '.')));
  return value + ' ' + labels[form === 'one' ? 0 : form === 'few' ? 1 : 2];
}

export function configValue(config, key, source) {
  const value = config[key];
  if (!['top_k', 'chunk_size', 'chunk_overlap'].includes(key)) return value;
  const match = String(value).trim().match(/^([+-]?\d+(?:[.,]\d+)?)\s*(.*)$/u);
  if (!match) return value;
  const [, number, inlineUnit] = match;
  if (key === 'top_k') return quantity(number, inlineUnit || config.top_k_unit || 'results') + ' на запрос';
  // Older records may carry the unit only in the quoted configuration line.
  const quoted = /^\s*(?:chunk size|chunk overlap|размер фрагмента|перекрытие фрагментов)\s*[:=]\s*(\d+)\s+(tokens?|bytes?|words?|characters?|chars?|токен(?:а|ов)?|байт(?:а|ов)?|слов(?:о|а)?|символ(?:а|ов)?)\s*[.]?\s*$/iu.exec(source || '');
  const quotedUnit = quoted && Number(quoted[1]) === Number(number) ? quoted[2] : '';
  return quantity(number, inlineUnit || config.chunk_unit || quotedUnit);
}

export const isRatio = m => ['%', 'fraction'].includes(m.unit);
export const formatPercent = value => value == null ? '—' : percent.format(value);

export function rawMetric(m) {
  if (m.raw == null) return '—';
  return m.raw + (m.unit === 'fraction' ? ' (доля)' : m.unit ? ' ' + m.unit : ' (единица не указана)');
}

export function normalizedMetric(m) {
  if (m.value == null) return '—';
  const value = Number(m.value).toLocaleString('ru', { minimumFractionDigits: 3, maximumFractionDigits: 8 });
  if (isRatio(m) || m.normalized_unit === 'fraction') return value + ' (доля)';
  return value + (m.normalized_unit ? ' ' + m.normalized_unit : ' (единица не указана)');
}

export function displayMetric(m) {
  if (isRatio(m) && m.value != null) return formatPercent(m.value);
  return m.normalized_unit && m.value != null ? normalizedMetric(m) : rawMetric(m);
}
