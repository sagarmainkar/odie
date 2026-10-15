/// <reference lib="webworker" />
import { precacheAndRoute } from "workbox-precaching";

declare let self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<{ url: string; revision: string | null }> };

precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener("push", (event) => {
  let data: { title?: string; body?: string; url?: string; tag?: string } = {};
  try { data = event.data?.json() ?? {}; } catch { data = { title: "Odie", body: event.data?.text() ?? "" }; }
  event.waitUntil(self.registration.showNotification(data.title ?? "Odie", {
    body: data.body ?? "", tag: data.tag ?? "odie", icon: "/icon-192.png", badge: "/icon-192.png", data: { url: data.url ?? "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
