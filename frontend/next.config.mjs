/** @type {import('next').NextConfig} */
import { API_BASE_URL, API_ROOT_URL } from './app/lib/api-config.js';

const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/backend/health',
        destination: `${API_ROOT_URL}/health`,
      },
      {
        source: '/api/backend/:path*',
        destination: `${API_BASE_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
