import type { MetadataRoute } from "next";

// Lets the portal be added to the phone's home screen and open full screen like an app.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "NIDA Enrolment",
    short_name: "NIDA Enrol",
    description: "Read NIDA Form 1A from photos and save the enrolment",
    start_url: "/enrolment/new",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0f1b2d",
    theme_color: "#123e74",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
