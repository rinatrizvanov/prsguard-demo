/** Base path of the static export ("" locally, "/prsguard-demo" on GitHub Pages). */
export const BASE_PATH: string = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Prefix a public-folder path with the base path. Every static fetch must go through this. */
export function assetUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_PATH}${p}`;
}
