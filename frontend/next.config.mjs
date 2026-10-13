/** @type {import('next').NextConfig} */
const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
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
