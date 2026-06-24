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
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
