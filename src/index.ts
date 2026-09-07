import { Container, getContainer } from "@cloudflare/containers";

export class YtDlpContainer extends Container {
  // Container tidur otomatis kalau tidak ada request (hemat biaya)
  defaultPort = 8080;
  sleepAfter = "5m";
}

interface Env {
  YTDLP_CONTAINER: DurableObjectNamespace<YtDlpContainer>;
  API_KEY: string; // set lewat `wrangler secret put API_KEY`
}

function unauthorized() {
  return new Response(JSON.stringify({ error: "Unauthorized" }), {
    status: 401,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // --- Auth sederhana pakai header X-API-Key ---
    const apiKey = request.headers.get("x-api-key");
    if (!env.API_KEY || apiKey !== env.API_KEY) {
      return unauthorized();
    }

    // Hanya izinkan endpoint yang memang kita definisikan di container
    const allowedPaths = ["/info", "/download", "/health"];
    if (!allowedPaths.includes(url.pathname)) {
      return new Response(JSON.stringify({ error: "Not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    }

    if (request.method !== "POST" && url.pathname !== "/health") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { "content-type": "application/json" },
      });
    }

    // Satu instance container global untuk sederhananya.
    // Untuk skala lebih besar, bisa dipakai id per-user/per-job.
    const container = getContainer(env.YTDLP_CONTAINER, "global-ytdlp");

    // Teruskan request apa adanya ke container (path, method, body, headers)
    return container.fetch(request);
  },
};
