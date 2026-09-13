// Service worker BLOCKHash : uniquement responsable de recevoir les
// notifications Web Push et de les afficher, meme onglet ferme. Ne met
// rien en cache (pas de mode hors-ligne) - hors scope de ce dashboard.

self.addEventListener("push", (event) => {
  let payload = { title: "BLOCKHash", body: "Nouvelle alerte" };
  try {
    if (event.data) payload = event.data.json();
  } catch {
    payload.body = event.data ? event.data.text() : payload.body;
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "BLOCKHash", {
      body: payload.body || "",
      icon: "favicon.ico",
      data: { url: payload.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
