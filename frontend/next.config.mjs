/**
 * Static export. Every byte the browser gets is a file on a CDN: the app holds no secrets, does
 * no server-side rendering, and reads everything from the API at runtime, so a Node server on
 * the hosting side would be a cost and an attack surface with nothing to do.
 *
 * The API base URL is baked in at build time from NEXT_PUBLIC_API_URL, defaulting to a local
 * uvicorn so `npm run dev` works against `make api` with no configuration.
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  reactStrictMode: true,
  trailingSlash: true,
};

export default nextConfig;
