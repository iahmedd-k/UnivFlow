/** @type {import('next').NextConfig} */
const PRODUCTION_API_URL = 'https://univlfow.koreacentral.cloudapp.azure.com/api/v1';
const LOCAL_API_URL = 'http://localhost:8000/api/v1';

const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
const rawApiUrl = (configuredApiUrl || (process.env.NODE_ENV === 'production' ? PRODUCTION_API_URL : LOCAL_API_URL))
  .trim()
  .replace(/\/+$/, '');

const apiBaseUrl = rawApiUrl.endsWith('/api/v1') ? rawApiUrl : `${rawApiUrl}/api/v1`;
const apiRootUrl = apiBaseUrl.replace(/\/api\/v1\/?$/, '');

const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/backend/health',
        destination: `${apiRootUrl}/health`,
      },
      {
        source: '/api/backend/:path*',
        destination: `${apiBaseUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
