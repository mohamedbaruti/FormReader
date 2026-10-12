/** @type {import('next').NextConfig} */
// The browser calls /pyapi/... on this app; Next.js forwards it to the Python
// Form Reader API, so no CORS set-up is needed. Change FORMREADER_API if the
// Python app runs on another computer or port.
const API = process.env.FORMREADER_API || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  experimental: { proxyTimeout: 180000 },   // reading a form can take a few seconds
  async rewrites() {
    return [{ source: "/pyapi/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
