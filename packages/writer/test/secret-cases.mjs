// All values are generated synthetic credential forms, never working credentials.
export const secretCases = () => [
  'sk-' + 'test'.repeat(8),
  'ghp_' + 'test'.repeat(8),
  'github_pat_' + 'test'.repeat(8),
  'xoxb-' + 'test-'.repeat(8),
  'AKIA' + 'A'.repeat(16),
  'ASIA' + 'B'.repeat(16),
  'AIza' + 'a'.repeat(35),
  'eyJ' + 'a'.repeat(12) + '.' + 'b'.repeat(12) + '.' + 'c'.repeat(12),
  'Bearer ' + 'synthetic-auth',
  ['-----BEGIN RSA PRIVATE KEY-----', 'synthetic-key-data', '-----END RSA PRIVATE KEY-----'].join('\n'),
  'api_key=synthetic-key-value',
  'https://synthetic:synthetic@example.invalid/',
];

export const ordinaryFields = { max_tokens: 42, inputTokens: 10, tokens_used: 3, token_count: 7,
  tokenizer: 'synthetic tokenizer', GIT_AUTHOR_NAME: 'Synthetic Author', monkey: 'ordinary word' };
