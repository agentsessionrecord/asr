// Pretty-prints JSON and JSON Lines examples for reading. Used by the site build and the white
// paper build, so examples look the same in both. Sources keep one record per line, as a stream
// does, and are what the validator checks.

// Widest line, in characters, that fits the site's code column without wrapping.
export const CODE_WIDTH = 60;

/** Splits JSON text into strings, punctuation and bare atoms (numbers, literals, "…" elisions). */
function tokenizeJson(src) {
  const tokens = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i++;
    } else if (c === '"') {
      let j = i + 1;
      while (j < src.length && src[j] !== '"') j += src[j] === '\\' ? 2 : 1;
      if (j >= src.length) return null;
      tokens.push({ t: 'leaf', v: src.slice(i, j + 1) });
      i = j + 1;
    } else if ('{}[],:'.includes(c)) {
      tokens.push({ t: c });
      i++;
    } else {
      let j = i;
      while (j < src.length && !/[\s{}[\],:"]/.test(src[j])) j++;
      tokens.push({ t: 'leaf', v: src.slice(i, j) });
      i = j;
    }
  }
  return tokens;
}

/**
 * Parses a sequence of JSON values. Tolerates bare elisions ("…") as object members or array
 * items, which the white paper uses. Returns null when the text is not of that shape.
 */
export function parseJsonValues(src) {
  const tokens = tokenizeJson(src);
  if (!tokens) return null;
  let p = 0;
  const value = () => {
    const tk = tokens[p++];
    if (!tk) throw new Error('unexpected end');
    if (tk.t === 'leaf') return { leaf: tk.v };
    if (tk.t !== '{' && tk.t !== '[') throw new Error(`unexpected ${tk.t}`);
    const close = tk.t === '{' ? '}' : ']';
    const items = [];
    while (tokens[p] && tokens[p].t !== close) {
      if (tk.t === '{' && tokens[p].t === 'leaf' && tokens[p + 1]?.t === ':') {
        const key = tokens[p].v;
        p += 2;
        items.push({ key, value: value() });
      } else {
        items.push({ value: value() });
      }
      if (tokens[p]?.t === ',') p++;
      else if (tokens[p]?.t !== close) throw new Error('expected a comma');
    }
    if (!tokens[p]) throw new Error('unclosed');
    p++;
    return { open: tk.t, close, items };
  };
  try {
    const values = [];
    while (p < tokens.length) values.push(value());
    return values.length ? values : null;
  } catch {
    return null;
  }
}

function inlineJson(node) {
  if ('leaf' in node) return node.leaf;
  const items = node.items.map((it) => (it.key ? `${it.key}: ` : '') + inlineJson(it.value));
  return `${node.open}${items.join(', ')}${node.close}`;
}

/** Pretty-prints a value, keeping any object or array on one line when it fits. */
export function prettyJson(node, indent = 0, column = 0, width = CODE_WIDTH) {
  const flat = inlineJson(node);
  if ('leaf' in node || node.items.length === 0 || column + flat.length + 1 <= width) return flat;
  const pad = ' '.repeat(indent + 2);
  const lines = node.items.map((it, i) => {
    const prefix = it.key ? `${it.key}: ` : '';
    const comma = i < node.items.length - 1 ? ',' : '';
    return pad + prefix + prettyJson(it.value, indent + 2, indent + 2 + prefix.length, width) + comma;
  });
  return `${node.open}\n${lines.join('\n')}\n${' '.repeat(indent)}${node.close}`;
}

/** Returns the values in `src` pretty-printed and separated by blank lines, or null if `src` does not parse. */
export function prettyJsonText(src, width = CODE_WIDTH) {
  const values = parseJsonValues(src);
  return values ? values.map((v) => prettyJson(v, 0, 0, width)).join('\n\n') : null;
}
