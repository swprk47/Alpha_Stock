// sw.js - Native App-like Push Notifications for Alpha Stock
const CACHE_NAME = 'alphastock-v1';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(clients.claim());
});

// 백그라운드 푸시 알림 표시 이벤트
self.addEventListener('push', (e) => {
  let data = { title: 'Alpha Stock', body: '새로운 알림이 도착했습니다.' };
  if (e.data) {
    try {
      data = e.data.json();
    } catch (err) {
      data.body = e.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: 'https://img.icons8.com/fluency/192/bullish.png',
    badge: 'https://img.icons8.com/fluency/96/bullish.png',
    vibrate: [200, 100, 200],
    data: { url: '/' }
  };

  e.waitUntil(self.registration.showNotification(data.title, options));
});

// 알림 배너 터치 시 앱 화면으로 즉시 이동
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === '/' && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/');
      }
    })
  );
});
