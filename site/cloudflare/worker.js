// Worker in front of the exported Mintlify site (Cloudflare Workers static assets).
// - Redirects www.agentsessionrecord.org to the bare domain.
// - Implements the client-side navigation rule from the export's README: a request carrying an
//   `RSC: 1` header or an `_rsc` query parameter gets the page's `index.txt` payload, so that
//   link clicks do not reload the whole page.
// Everything else is served from the static assets.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname.startsWith('www.')) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    const isRsc = request.headers.get('RSC') === '1' || url.searchParams.has('_rsc');
    if (isRsc && !/\.[a-z0-9]+$/i.test(url.pathname)) {
      const payload = new URL(`${url.pathname.replace(/\/$/, '')}/index.txt`, url.origin);
      const response = await env.ASSETS.fetch(payload);
      if (response.ok) {
        const headers = new Headers(response.headers);
        headers.set('Content-Type', 'text/x-component');
        headers.set('Vary', 'RSC');
        headers.set('Cache-Control', 'no-cache');
        return new Response(response.body, { status: 200, headers });
      }
    }
    return env.ASSETS.fetch(request);
  },
};
