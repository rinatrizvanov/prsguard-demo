// Static export. The hosted build needs nothing but the files in `out/`.
// NEXT_PUBLIC_BASE_PATH is "" locally and "/prsguard-demo" for GitHub Pages.

function normaliseBasePath(value) {
  const trimmed = (value || "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

const basePath = normaliseBasePath(process.env.NEXT_PUBLIC_BASE_PATH);

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  basePath,
  assetPrefix: basePath || undefined,
  reactStrictMode: true,
  poweredByHeader: false,
  env: {
    // Re-export the normalised value so client code and asset URLs agree exactly.
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
