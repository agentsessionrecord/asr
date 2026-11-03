// RFC 4648 alphabet and padding grammar. Do not decode or restrict padding bits:
// the format accepts every spelling accepted by its alphabet/length grammar.
// This loop takes linear time and constant stack space, including large media.
export function isBase64(value) {
  if (value.length % 4 !== 0) return false;
  let end = value.length;
  if (end && value.charCodeAt(end - 1) === 61) end--;
  if (end && value.charCodeAt(end - 1) === 61) end--;
  for (let index = 0; index < end; index++) {
    const code = value.charCodeAt(index);
    if (!((code >= 65 && code <= 90) || (code >= 97 && code <= 122) ||
      (code >= 48 && code <= 57) || code === 43 || code === 47)) return false;
  }
  return true;
}
