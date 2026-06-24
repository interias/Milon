import type { NextConfig } from "next";

// Backend über den Next-Dev-Server proxien: das Handy spricht nur mit dem Frontend-Port
// (Node, im Heim-WLAN erreichbar), Next leitet `/api/*` serverseitig per Loopback an das
// FastAPI-Backend weiter. So entfällt sowohl eine Firewall-Freigabe für :8000 als auch CORS.
const API = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Dev-Server-Zugriff (HMR/Live-Reload) von anderen Geräten im Heim-WLAN über die LAN-IP
  // erlauben — sonst blockt Next 16 den cross-origin Dev-Request und die HMR-WebSocket
  // schlägt fehl. Eigene IP(s) hier ergänzen, falls sie sich ändert.
  allowedDevOrigins: ["192.168.0.26"],
  // Der Rewrite-Proxy hat per Default nur 30 s Timeout (Next: proxyTimeout || 30000).
  // Der Tool-Calling-Coach (/coach/ask) braucht bei vielen Tool-Aufrufen 20–40 s → sonst
  // antwortet der Proxy mit 500, obwohl das Backend noch sauber liefert. Auf 2 min anheben.
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
