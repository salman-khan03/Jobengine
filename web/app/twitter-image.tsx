// Twitter/X reads its own `twitter-image` file convention and does not
// reliably fall back to `opengraph-image` — rather than assume it does,
// this re-exports the same generated image so both surfaces are covered
// explicitly. See opengraph-image.tsx for the actual design.
export { alt, size, contentType, default } from "./opengraph-image";
