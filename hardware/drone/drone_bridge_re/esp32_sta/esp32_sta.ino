#include <WiFi.h>
#include <WiFiUdp.h>

#include "serial_frame.h"
#include "forward_types.h"

// Needed for country/channel configuration.
#include "esp_wifi.h"
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <lwip/sockets.h>
#include <lwip/inet.h>
#include <netinet/tcp.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ESP32 #2: drone STA endpoint.
// - Joins real drone SSID (RADCLOFPV_839819 by default).
// - Opens outbound UDP/TCP to the drone (gateway IP assumed 192.168.0.1).
// - Bridges traffic between Wi-Fi and USB serial frames.

#ifndef STA_LED_PIN
  #ifdef LED_BUILTIN
    #define STA_LED_PIN LED_BUILTIN
  #else
    // Most ESP32 dev boards route the onboard (often blue) LED to GPIO2.
    #define STA_LED_PIN 2
  #endif
#endif

#ifndef STA_LED_ACTIVE_LOW
  #define STA_LED_ACTIVE_LOW 0
#endif

static const char *DRONE_SSID = "RADCLOFPV_839819";
static const char *DRONE_PASS = "";  // typically open

static SfDecoder dec;
static uint8_t rx_payload[2048];

static IPAddress drone_ip(192, 168, 0, 1);

static uint32_t udp_tx_to_drone = 0;
// Count only packets forwarded back over serial (excludes intentionally dropped video).
static uint32_t udp_rx_from_drone = 0;
static uint32_t udp_rx_drop_video = 0;

// Drone streams JPEG video from UDP src port 7070 to our mirrored local UDP port
// (typically the phone's UDP src port like 6000). Forwarding that over 921600 UART
// is not feasible; it will starve control-plane traffic. Drop it here.
static const bool DROP_DRONE_VIDEO_7070 = true;
static const uint16_t DRONE_VIDEO_SRC_PORT = 7070;

static volatile uint8_t last_disc_reason = 0;

static void wifi_set_country_1_to_13() {
  // Some of these drones advertise on ch 12/13. Many ESP32 builds default to US (1-11).
  // Setting 1-13 makes scanning/connecting possible in more cases.
  wifi_country_t c{};
  memcpy(c.cc, "00", 2);  // world
  c.schan = 1;
  c.nchan = 13;
  c.policy = WIFI_COUNTRY_POLICY_MANUAL;
  esp_err_t rc = esp_wifi_set_country(&c);
  sf_logf("wifi: set_country schan=%u nchan=%u rc=%d", (unsigned)c.schan, (unsigned)c.nchan, (int)rc);
}

static void wifi_begin_drone() {
  // Arduino-ESP32 behaves more reliably for open networks if we use the
  // single-argument overload (passphrase == NULL) instead of "".
  if (DRONE_PASS && DRONE_PASS[0]) WiFi.begin(DRONE_SSID, DRONE_PASS);
  else WiFi.begin(DRONE_SSID);
}

static int wifi_scan_log_radclo(bool only_target) {
  // Scan can fail with -2 if WiFi is busy connecting; ensure we are disconnected first.
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, false);
  delay(200);
  int n = WiFi.scanNetworks(false /*async*/, true /*show_hidden*/);
  sf_logf("wifi: scan n=%d", n);
  if (n <= 0) {
    WiFi.scanDelete();
    WiFi.setAutoReconnect(true);
    return n;
  }

  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    if (only_target) {
      if (ssid != String(DRONE_SSID)) continue;
    } else {
      if (!ssid.startsWith("RADCLOFPV_")) continue;
    }
    const uint8_t *b = WiFi.BSSID(i);
    char bssid[32];
    if (b) snprintf(bssid, sizeof(bssid), "%02x:%02x:%02x:%02x:%02x:%02x", b[0], b[1], b[2], b[3], b[4], b[5]);
    else snprintf(bssid, sizeof(bssid), "??");
    sf_logf("wifi: ap ssid=%s rssi=%ld ch=%ld enc=%d bssid=%s",
            ssid.c_str(),
            (long)WiFi.RSSI(i),
            (long)WiFi.channel(i),
            (int)WiFi.encryptionType(i),
            bssid);
  }

  WiFi.scanDelete();
  WiFi.setAutoReconnect(true);
  return n;
}

static void led_set(bool on) {
  bool level = on;
#if STA_LED_ACTIVE_LOW
  level = !level;
#endif
  digitalWrite(STA_LED_PIN, level ? HIGH : LOW);
}

static void led_poll() {
  // Solid ON when connected; blink otherwise.
  static uint32_t last_toggle_ms = 0;
  static bool blink_state = false;
  if (WiFi.status() == WL_CONNECTED) {
    led_set(true);
    return;
  }
  uint32_t now = millis();
  // Faster blink while connecting, slower when fully disconnected.
  uint32_t period_ms = (WiFi.status() == WL_DISCONNECTED) ? 500 : 200;
  if (now - last_toggle_ms >= period_ms) {
    last_toggle_ms = now;
    blink_state = !blink_state;
    led_set(blink_state);
  }
}

static void sf_log(const char *msg) {
  if (!msg) return;
  sf_send(Serial, SF_LOG, 0, 0, (const uint8_t *)msg, (uint16_t)strlen(msg));
}

static void sf_logf(const char *fmt, ...) {
  char buf[256];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  sf_log(buf);
}

struct TcpOut {
  bool active = false;
  uint16_t conn_id = 0;
  uint16_t port = 0;
  int fd = -1;
  bool connecting = false;           // connect task in progress
  bool want_open = false;            // keep retrying until connected or SF_TCP_CLOSE
  uint8_t bind_mode = 0;             // 0=bind local port to conn_id, 1=ephemeral
  volatile bool connect_done = false;
  volatile bool connect_ok = false;
  volatile int connect_errno = 0;
  volatile uint16_t connect_local_port = 0;
  volatile uint8_t connect_bind_ok = 0;
  volatile uint8_t connect_bind_mode = 0;
  volatile uint32_t connect_dt_ms = 0;
  TaskHandle_t connect_task = nullptr;
  volatile uint32_t gen = 0;         // increments each open_req; prevents stale connect task results
  uint32_t next_retry_ms = 0;
  uint32_t retry_backoff_ms = 250;
  uint16_t pending_len = 0;
  bool pending_overflow_logged = false;
};

static const int MAX_TCP = 6;
static TcpOut tcp_out[MAX_TCP];

static const uint32_t TCP_CONNECT_TIMEOUT_MS = 4000;
static const uint16_t TCP_PENDING_CAP = 4096;
static uint8_t tcp_pending[MAX_TCP][TCP_PENDING_CAP];

static void tcp_close_fd(int &fd) {
  if (fd >= 0) {
    lwip_close(fd);
    fd = -1;
  }
}

static int tcp_set_nonblock(int fd, bool on) {
  int flags = fcntl(fd, F_GETFL, 0);
  if (flags < 0) return -1;
  if (on) flags |= O_NONBLOCK;
  else flags &= ~O_NONBLOCK;
  return fcntl(fd, F_SETFL, flags);
}

static void tcp_connect_task_fn(void *arg) {
  TcpOut *t = (TcpOut *)arg;
  const uint32_t my_gen = t->gen;
  const uint16_t my_conn = t->conn_id;
  const uint16_t my_port = t->port;

  // Defensive defaults.
  t->connect_ok = false;
  t->connect_errno = 0;
  t->connect_local_port = 0;
  t->connect_bind_ok = 0;
  t->connect_bind_mode = t->bind_mode;
  t->connect_dt_ms = 0;

  uint32_t start = millis();

  // Use lwIP sockets directly so we can bind the local source port equal to the destination port.
  // Some drone firmwares appear to hard-code peer ports (e.g. expect controller at 192.168.0.2:7060).
  int fd0 = lwip_socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd0 < 0) {
    t->connect_errno = errno;
    t->connect_done = true;
    t->connect_task = nullptr;
    vTaskDelete(nullptr);
  }
  // Publish the connecting socket fd immediately so SF_TCP_CLOSE can cancel and close it.
  // This avoids leaking bound ports and hitting EADDRINUSE on rapid retries.
  t->fd = fd0;

  int one = 1;
  lwip_setsockopt(t->fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
  lwip_setsockopt(t->fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
  // Abortive close to reduce TIME_WAIT impact on fixed source-port binds.
  struct linger ling;
  ling.l_onoff = 1;
  ling.l_linger = 0;
  lwip_setsockopt(t->fd, SOL_SOCKET, SO_LINGER, &ling, sizeof(ling));

  // Best-effort bind to a specific local port (some drones appear to care).
  struct sockaddr_in local {};
  local.sin_family = AF_INET;
  local.sin_addr.s_addr = htonl(INADDR_ANY);
  if (t->bind_mode == 0) {
    // Mirror the conn_id (stable per port in our AP build) so the drone sees a controller
    // coming from 192.168.0.2:<port>.
    local.sin_port = htons(my_conn);
    if (lwip_bind(t->fd, (struct sockaddr *)&local, sizeof(local)) == 0) {
      t->connect_bind_ok = 1;
    }
  }
  if (!t->connect_bind_ok) {
    // Fall back to ephemeral.
    local.sin_port = htons(0);
    (void)lwip_bind(t->fd, (struct sockaddr *)&local, sizeof(local));
  }

  // Record the actual chosen local port (useful when debugging drones that appear
  // to whitelist controller ports).
  struct sockaddr_in got_local {};
  socklen_t got_len = sizeof(got_local);
  if (lwip_getsockname(t->fd, (struct sockaddr *)&got_local, &got_len) == 0) {
    t->connect_local_port = (uint16_t)ntohs(got_local.sin_port);
  }

  (void)tcp_set_nonblock(t->fd, true);

  struct sockaddr_in remote {};
  remote.sin_family = AF_INET;
  remote.sin_port = htons(my_port);
  remote.sin_addr.s_addr = inet_addr(drone_ip.toString().c_str());

  int rc = lwip_connect(t->fd, (struct sockaddr *)&remote, sizeof(remote));
  int e = errno;
  if (rc != 0 && (e == EINPROGRESS || e == EALREADY)) {
    // If we got cancelled while connecting, stop promptly.
    if (!t->active || t->gen != my_gen || t->conn_id != my_conn || t->port != my_port || t->fd < 0) {
      tcp_close_fd(t->fd);
      t->connect_task = nullptr;
      vTaskDelete(nullptr);
    }
    fd_set wfds;
    FD_ZERO(&wfds);
    FD_SET(t->fd, &wfds);
    struct timeval tv {};
    tv.tv_sec = (int)(TCP_CONNECT_TIMEOUT_MS / 1000);
    tv.tv_usec = (int)((TCP_CONNECT_TIMEOUT_MS % 1000) * 1000);
    int sel = lwip_select(t->fd + 1, nullptr, &wfds, nullptr, &tv);
    if (sel > 0) {
      int soerr = 0;
      socklen_t sl = sizeof(soerr);
      lwip_getsockopt(t->fd, SOL_SOCKET, SO_ERROR, &soerr, &sl);
      if (soerr == 0) {
        rc = 0;
      } else {
        rc = -1;
        e = soerr;
      }
    } else if (sel == 0) {
      rc = -1;
      e = ETIMEDOUT;
    } else {
      rc = -1;
      e = errno;
    }
  }

  uint32_t dt = millis() - start;
  t->connect_dt_ms = dt;

  if (rc != 0) tcp_close_fd(t->fd);

  // Slot might have been closed or reused; discard stale results.
  if (!t->active || t->gen != my_gen || t->conn_id != my_conn || t->port != my_port) {
    tcp_close_fd(t->fd);
    t->connect_task = nullptr;
    vTaskDelete(nullptr);
  }

  if (rc == 0 && t->fd >= 0) {
    t->connect_ok = true;
    t->connect_errno = 0;
  } else {
    t->connect_ok = false;
    t->connect_errno = e ? e : ETIMEDOUT;
  }
  t->connect_done = true;
  t->connect_task = nullptr;
  vTaskDelete(nullptr);
}

struct UdpFlow {
  bool active = false;
  uint16_t local_port = 0;  // phone source port
  WiFiUDP udp;
};

static const int MAX_UDP_FLOWS = 8;
static UdpFlow udp_flows[MAX_UDP_FLOWS];

static void on_wifi_event(WiFiEvent_t event, WiFiEventInfo_t info) {
  // Keep this numeric and verbose; reason codes vary by core version.
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_START:
      sf_log("wifi: STA_START");
      break;
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      sf_log("wifi: STA_CONNECTED");
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      last_disc_reason = (uint8_t)info.wifi_sta_disconnected.reason;
      sf_logf("wifi: STA_DISCONNECTED reason=%u", (unsigned)info.wifi_sta_disconnected.reason);
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      sf_logf("wifi: GOT_IP ip=%s gw=%s",
              WiFi.localIP().toString().c_str(),
              WiFi.gatewayIP().toString().c_str());
      break;
    default:
      // Other events are less useful; keep noise down.
      break;
  }
}

static void send_hello() {
  const char *who = "STA";
  sf_send(Serial, SF_HELLO, 0, 0, (const uint8_t *)who, (uint16_t)strlen(who));
}

static void wifi_join() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.onEvent(on_wifi_event);
  wifi_set_country_1_to_13();

  sf_logf("wifi: begin ssid=%s", DRONE_SSID);
  wifi_begin_drone();

  uint32_t start = millis();
  uint32_t last_wait_log = 0;
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    led_poll();  // show activity even before loop() starts
    uint32_t now = millis();
    if (now - last_wait_log > 1000) {
      last_wait_log = now;
      sf_logf("wifi: join_wait status=%d rssi=%d last_reason=%u",
              (int)WiFi.status(), (int)WiFi.RSSI(), (unsigned)last_disc_reason);
    }
    delay(50);
  }

  wl_status_t st = WiFi.status();
  sf_logf("wifi: status=%d rssi=%d", (int)st, (int)WiFi.RSSI());
  if (st == WL_CONNECTED) {
    sf_logf("wifi: connected ip=%s gw=%s mask=%s dns=%s",
            WiFi.localIP().toString().c_str(),
            WiFi.gatewayIP().toString().c_str(),
            WiFi.subnetMask().toString().c_str(),
            WiFi.dnsIP().toString().c_str());
    IPAddress gw = WiFi.gatewayIP();
    if ((uint32_t)gw != 0) drone_ip = gw;
    sf_logf("drone: ip=%s", drone_ip.toString().c_str());
  } else {
    sf_log("wifi: not connected after initial wait");

    // Quick scan on failure so we can tell if the ESP32 can even see the drone SSID.
    wifi_scan_log_radclo(false /*only_target*/);
  }
}

static void wifi_ensure_connected() {
  static uint32_t last_try_ms = 0;
  if (WiFi.status() == WL_CONNECTED) return;
  uint32_t now = millis();

  if (now - last_try_ms < 3000) return;
  last_try_ms = now;
  sf_logf("wifi: reconnect status=%d", (int)WiFi.status());
  // If we appear to have no SSID available, scan occasionally to show what we can see.
  if (WiFi.status() == WL_NO_SSID_AVAIL) {
    wifi_scan_log_radclo(true /*only_target*/);
  }
  WiFi.disconnect(false, false);
  delay(100);
  wifi_begin_drone();
}

static void wifi_status_heartbeat() {
  static uint32_t last_ms = 0;
  uint32_t now = millis();
  if (now - last_ms < 5000) return;
  last_ms = now;
  sf_logf("wifi: hb ssid=%s status=%d rssi=%d ip=%s gw=%s drone_ip=%s udp_tx=%lu udp_rx=%lu udp_drop_video=%lu",
          WiFi.SSID().c_str(),
          (int)WiFi.status(),
          (int)WiFi.RSSI(),
          WiFi.localIP().toString().c_str(),
          WiFi.gatewayIP().toString().c_str(),
          drone_ip.toString().c_str(),
          (unsigned long)udp_tx_to_drone,
          (unsigned long)udp_rx_from_drone,
          (unsigned long)udp_rx_drop_video);
}

static TcpOut *find_tcp(uint16_t conn_id) {
  for (int i = 0; i < MAX_TCP; i++) {
    if (tcp_out[i].active && tcp_out[i].conn_id == conn_id) return &tcp_out[i];
  }
  return nullptr;
}

static TcpOut *find_tcp_by_port(uint16_t port) {
  for (int i = 0; i < MAX_TCP; i++) {
    if (tcp_out[i].active && tcp_out[i].port == port) return &tcp_out[i];
  }
  return nullptr;
}

static TcpOut *alloc_tcp(uint16_t conn_id, uint16_t port) {
  for (int i = 0; i < MAX_TCP; i++) {
    if (!tcp_out[i].active) {
      tcp_out[i].active = true;
      tcp_out[i].conn_id = conn_id;
      tcp_out[i].port = port;
      tcp_out[i].fd = -1;
      tcp_out[i].connecting = false;
      tcp_out[i].want_open = false;
      tcp_out[i].bind_mode = 0;
      tcp_out[i].connect_done = false;
      tcp_out[i].connect_ok = false;
      tcp_out[i].connect_errno = 0;
      tcp_out[i].connect_local_port = 0;
      tcp_out[i].connect_bind_ok = 0;
      tcp_out[i].connect_bind_mode = 0;
      tcp_out[i].connect_dt_ms = 0;
      tcp_out[i].connect_task = nullptr;
      tcp_out[i].gen = 0;
      tcp_out[i].next_retry_ms = 0;
      tcp_out[i].retry_backoff_ms = 250;
      tcp_out[i].pending_len = 0;
      tcp_out[i].pending_overflow_logged = false;
      return &tcp_out[i];
    }
  }
  return nullptr;
}

static void free_tcp(TcpOut *t) {
  if (!t) return;
  if (t->connect_task) {
    // We don't hard-kill the task; it will finish quickly due to short timeout.
    // Mark inactive so its result will be ignored.
    t->connect_task = nullptr;
  }
  tcp_close_fd(t->fd);
  t->active = false;
  t->conn_id = 0;
  t->port = 0;
  t->connecting = false;
  t->want_open = false;
  t->bind_mode = 0;
  t->connect_done = false;
  t->connect_ok = false;
  t->connect_errno = 0;
  t->gen = 0;
  t->connect_local_port = 0;
  t->connect_bind_ok = 0;
  t->connect_bind_mode = 0;
  t->connect_dt_ms = 0;
  t->next_retry_ms = 0;
  t->retry_backoff_ms = 250;
  t->pending_len = 0;
  t->pending_overflow_logged = false;
}

static UdpFlow *find_udp_flow(uint16_t local_port) {
  for (int i = 0; i < MAX_UDP_FLOWS; i++) {
    if (udp_flows[i].active && udp_flows[i].local_port == local_port) return &udp_flows[i];
  }
  return nullptr;
}

static UdpFlow *ensure_udp_flow(uint16_t local_port) {
  UdpFlow *f = find_udp_flow(local_port);
  if (f) return f;
  for (int i = 0; i < MAX_UDP_FLOWS; i++) {
    if (!udp_flows[i].active) {
      udp_flows[i].active = true;
      udp_flows[i].local_port = local_port;
      udp_flows[i].udp.begin(local_port);
      return &udp_flows[i];
    }
  }
  return nullptr;
}

static void poll_udp_flows() {
  for (int i = 0; i < MAX_UDP_FLOWS; i++) {
    UdpFlow *f = &udp_flows[i];
    if (!f->active) continue;
    int n = f->udp.parsePacket();
    if (n <= 0) continue;
    if (n > (int)sizeof(rx_payload)) n = (int)sizeof(rx_payload);
    uint16_t from_port = (uint16_t)f->udp.remotePort();  // drone src port (e.g. 40000/50000/7070)
    int r = f->udp.read(rx_payload, n);
    if (r <= 0) continue;

    // If the drone's IP isn't the gateway for some reason, learn it from actual traffic.
    // (Many of these drones *are* the gateway; this is a safety net.)
    IPAddress rip = f->udp.remoteIP();
    if ((uint32_t)rip != 0 && (uint32_t)rip != (uint32_t)drone_ip) {
      drone_ip = rip;
      sf_logf("drone: learned_ip=%s (from udp)", drone_ip.toString().c_str());
    }

    static bool logged_first_nonvideo = false;
    static bool logged_drop_video = false;
    if (DROP_DRONE_VIDEO_7070 && from_port == DRONE_VIDEO_SRC_PORT) {
      udp_rx_drop_video++;
      if (!logged_drop_video) {
        logged_drop_video = true;
        sf_logf("udp: drop_video from=%s:%u -> local=%u len=%d (not forwarded over serial)",
                f->udp.remoteIP().toString().c_str(),
                (unsigned)from_port,
                (unsigned)f->local_port,
                r);
      }
      continue;
    }

    if (!logged_first_nonvideo) {
      logged_first_nonvideo = true;
      sf_logf("udp: first_rx_from_drone(nonvideo) from=%s:%u -> local=%u len=%d",
              f->udp.remoteIP().toString().c_str(),
              (unsigned)from_port,
              (unsigned)f->local_port,
              r);
    }

    uint16_t to_phone_port = f->local_port;              // phone port we mirrored
    // Frame back:
    //   conn_id = phone destination port
    //   port    = UDP source port (40000/50000)
    sf_send(Serial, SF_UDP, to_phone_port, from_port, rx_payload, (uint16_t)r);
    udp_rx_from_drone++;
  }
}

static void handle_serial_frame(const SfHeader &h, const uint8_t *payload, uint16_t paylen) {
  if (h.type == SF_UDP) {
    // Inbound from phone-side:
    //   conn_id = phone source port
    //   port    = drone destination port (40000/50000)
    uint16_t phone_port = h.conn;
    uint16_t dst_port = h.port;
    UdpFlow *f = ensure_udp_flow(phone_port);
    if (!f) return;
    f->udp.beginPacket(drone_ip, dst_port);
    if (paylen && payload) f->udp.write(payload, paylen);
    f->udp.endPacket();
    udp_tx_to_drone++;
    return;
  }

  if (h.type == SF_TCP_OPEN) {
    // Open outbound to drone.
    uint16_t conn_id = h.conn;
    uint16_t port = h.port;
    sf_logf("tcp: open_req conn=%u port=%u wifi_status=%d rssi=%d ip=%s gw=%s drone_ip=%s",
            (unsigned)conn_id,
            (unsigned)port,
            (int)WiFi.status(),
            (int)WiFi.RSSI(),
            WiFi.localIP().toString().c_str(),
            WiFi.gatewayIP().toString().c_str(),
            drone_ip.toString().c_str());
    TcpOut *t = find_tcp(conn_id);
    if (!t) t = alloc_tcp(conn_id, port);
    if (!t) {
      sf_send(Serial, SF_TCP_OPEN_FAIL, conn_id, port, nullptr, 0);
      return;
    }
    t->want_open = true;
    t->port = port;

    // If we already have a working connection for this (stable) conn_id, just
    // acknowledge it so the AP can keep the phone socket stable.
    if (!t->connecting && t->fd >= 0) {
      sf_logf("tcp: open_reuse conn=%u port=%u local=%u", (unsigned)t->conn_id, (unsigned)t->port, (unsigned)t->connect_local_port);
      sf_send(Serial, SF_TCP_OPEN_OK, conn_id, port, nullptr, 0);
      return;
    }

    // Otherwise, kick the connect state machine. Don't smash backoff on repeated
    // SF_TCP_OPENs from the AP while the app is reconnecting.
    if (!t->connecting && t->fd < 0) {
      t->next_retry_ms = 0;
    }
    return;
  }

  if (h.type == SF_TCP_DATA) {
    TcpOut *t = find_tcp(h.conn);
    if (!t) return;
    if (t->connecting) {
      // Buffer early data until connect completes (best-effort).
      if (!payload || paylen == 0) return;
      uint16_t room = (t->pending_len < TCP_PENDING_CAP) ? (TCP_PENDING_CAP - t->pending_len) : 0;
      if (room == 0) {
        if (!t->pending_overflow_logged) {
          t->pending_overflow_logged = true;
          sf_logf("tcp: pending_overflow conn=%u port=%u cap=%u", (unsigned)t->conn_id, (unsigned)t->port, (unsigned)TCP_PENDING_CAP);
        }
        return;
      }
      uint16_t n = paylen;
      if (n > room) n = room;
      int idx = -1;
      for (int i = 0; i < MAX_TCP; i++) if (tcp_out[i].active && &tcp_out[i] == t) { idx = i; break; }
      if (idx >= 0) {
        memcpy(&tcp_pending[idx][t->pending_len], payload, n);
        t->pending_len += n;
      }
      return;
    }
    if (t->fd < 0) return;
    if (paylen && payload) (void)lwip_send(t->fd, payload, paylen, 0);
    return;
  }

  if (h.type == SF_TCP_CLOSE) {
    TcpOut *t = find_tcp(h.conn);
    if (!t) return;
    free_tcp(t);
    return;
  }
}

static void poll_serial() {
  SfHeader h;
  uint16_t paylen = 0;
  while (dec.poll(Serial, h, rx_payload, sizeof(rx_payload), paylen)) {
    handle_serial_frame(h, rx_payload, paylen);
  }
}

static void poll_tcp_out() {
  for (int i = 0; i < MAX_TCP; i++) {
    TcpOut *t = &tcp_out[i];
    if (!t->active) continue;

    if (t->want_open && !t->connecting && t->fd < 0 && WiFi.status() == WL_CONNECTED) {
      uint32_t now = millis();
      if (now >= t->next_retry_ms) {
        t->connecting = true;
        t->connect_done = false;
        t->connect_ok = false;
        t->connect_errno = 0;
        t->connect_local_port = 0;
        t->connect_bind_ok = 0;
        t->connect_dt_ms = 0;
        t->gen++;

        BaseType_t ok = xTaskCreatePinnedToCore(
            tcp_connect_task_fn,
            "tcpconn",
            4096,
            (void *)t,
            1,
            &t->connect_task,
            1);
        sf_logf("tcp: connect_spawn conn=%u port=%u rc=%d", (unsigned)t->conn_id, (unsigned)t->port, (int)ok);
        if (ok != pdPASS) {
          t->connecting = false;
          t->next_retry_ms = now + 1000;
        }
      }
    }

    if (t->connecting) {
      if (!t->connect_done) continue;
      t->connecting = false;
      int e = t->connect_errno;
      const char *es = strerror(e);
      if (t->connect_ok && t->fd >= 0) {
        sf_logf("tcp: open_ok conn=%u port=%u dt=%lums bind_mode=%u bind_ok=%u local=%u",
                (unsigned)t->conn_id,
                (unsigned)t->port,
                (unsigned long)t->connect_dt_ms,
                (unsigned)t->connect_bind_mode,
                (unsigned)t->connect_bind_ok,
                (unsigned)t->connect_local_port);
        sf_send(Serial, SF_TCP_OPEN_OK, t->conn_id, t->port, nullptr, 0);
        if (t->pending_len) {
          (void)lwip_send(t->fd, tcp_pending[i], t->pending_len, 0);
          sf_logf("tcp: flushed_pending conn=%u port=%u n=%u", (unsigned)t->conn_id, (unsigned)t->port, (unsigned)t->pending_len);
          t->pending_len = 0;
        }
        t->retry_backoff_ms = 250;
      } else {
        sf_logf("tcp: open_fail conn=%u port=%u dt=%lums bind_mode=%u bind_ok=%u local=%u errno=%d err=%s",
                (unsigned)t->conn_id,
                (unsigned)t->port,
                (unsigned long)t->connect_dt_ms,
                (unsigned)t->connect_bind_mode,
                (unsigned)t->connect_bind_ok,
                (unsigned)t->connect_local_port,
                e, es ? es : "?");
        sf_send(Serial, SF_TCP_OPEN_FAIL, t->conn_id, t->port, nullptr, 0);
        // Keep the slot and retry in the background. This reduces phone-side reconnect
        // thrash and lets us catch drones that only open TCP services after UDP setup.
        t->fd = -1;
        uint32_t now = millis();
        if (e == ETIMEDOUT) t->bind_mode = (t->bind_mode == 0) ? 1 : 0;
        if (t->retry_backoff_ms < 5000) t->retry_backoff_ms *= 2;
        t->next_retry_ms = now + t->retry_backoff_ms;
      }
      continue;
    }

    if (t->fd < 0) {
      // No socket right now. If we still want this connection, stay idle and let
      // the retry scheduler above spawn a new connect attempt.
      if (!t->want_open) {
        sf_send(Serial, SF_TCP_CLOSE, t->conn_id, t->port, nullptr, 0);
        free_tcp(t);
      }
      continue;
    }

    while (true) {
      int r = lwip_recv(t->fd, rx_payload, sizeof(rx_payload), MSG_DONTWAIT);
      if (r > 0) {
        sf_send(Serial, SF_TCP_DATA, t->conn_id, t->port, rx_payload, (uint16_t)r);
        continue;
      }
      if (r == 0) {
        sf_send(Serial, SF_TCP_CLOSE, t->conn_id, t->port, nullptr, 0);
        free_tcp(t);
      } else {
        int ee = errno;
        if (ee != EWOULDBLOCK && ee != EAGAIN) {
          sf_send(Serial, SF_TCP_CLOSE, t->conn_id, t->port, nullptr, 0);
          free_tcp(t);
        }
      }
      break;
    }
  }
}

void setup() {
  Serial.begin(921600);
  delay(200);

  pinMode(STA_LED_PIN, OUTPUT);
  led_set(false);

  wifi_join();
  send_hello();
}

void loop() {
  static uint32_t last_hello_ms = 0;
  uint32_t now = millis();
  if (now - last_hello_ms > 2000) {
    last_hello_ms = now;
    send_hello();
  }

  led_poll();
  wifi_status_heartbeat();
  wifi_ensure_connected();

  poll_serial();
  poll_tcp_out();
  poll_udp_flows();
  delay(1);
}
