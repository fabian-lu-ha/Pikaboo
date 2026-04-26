import { Config } from "@remotion/cli/config";

// JPEG keeps frames small while preserving photographic quality (we render
// images, not flat UI). H.264 is the universal default for marketing assets
// across all the platforms the backend ships to.
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(90);
Config.setCodec("h264");
Config.setOverwriteOutput(true);
Config.setConcurrency(null); // null = let Remotion auto-detect based on cores
