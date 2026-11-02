import type { NextConfig } from 'next';
const nextConfig: NextConfig =
  process.env.LOCAL_STATIC === '1' ? { output: 'export' } : {};
export default nextConfig;
