/**
 * Cloudflare Worker — IDX securities-stock list proxy.
 *
 * IDX (idx.co.id) blocks datacenter/NAS IPs with Cloudflare 403. This Worker
 * runs on Cloudflare's edge (non-DC egress) and proxies the official
 * GetSecuritiesStock JSON so the MAI-IDX-Signal universe updater can reach it.
 *
 * Deploy:  wrangler deploy
 * Use:     GET https://<worker>.workers.dev/   -> IDX JSON verbatim
 *          Optional ?key=<SECRET> if PROXY_KEY env var is set (recommended).
 */
const IDX_URL =
  "https://www.idx.co.id/primary/Helper/GetEmiten?emitenType=s";

export default {
  async fetch(request, env) {
    // Optional shared-secret gate.
    if (env.PROXY_KEY) {
      const url = new URL(request.url);
      if (url.searchParams.get("key") !== env.PROXY_KEY) {
        return new Response(JSON.stringify({ error: "unauthorized" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        });
      }
    }

    try {
      const upstream = await fetch(IDX_URL, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
          Accept: "application/json, text/javascript, */*; q=0.01",
          "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
          "X-Requested-With": "XMLHttpRequest",
          Referer:
            "https://www.idx.co.id/en/market-data/stocks-data/stock-list/",
          Origin: "https://www.idx.co.id",
          "Sec-Fetch-Dest": "empty",
          "Sec-Fetch-Mode": "cors",
          "Sec-Fetch-Site": "same-origin",
        },
        cf: { cacheTtl: 1800, cacheEverything: true },
      });

      const body = await upstream.text();
      return new Response(body, {
        status: upstream.status,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "public, max-age=3600",
          "access-control-allow-origin": "*",
        },
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ error: "upstream_fetch_failed", detail: String(err) }),
        { status: 502, headers: { "content-type": "application/json" } },
      );
    }
  },
};
