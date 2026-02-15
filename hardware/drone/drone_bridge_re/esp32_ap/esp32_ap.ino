#include <WiFi.h>
#include <WiFiUdp.h>

#include "serial_frame.h"

// ESP32 #1: spoof AP endpoint.
// - AP SSID: RADCLOFPV_676767
// - AP IP: 192.168.0.1/24
// - Listen: UDP 40000/50000, TCP 7060/8060/9060
// - Forward all network traffic as framed messages over USB serial.

#ifndef AP_LOG_LEVEL
// 0 = silent, 1 = important events, 2 = verbose (may hurt latency)
#define AP_LOG_LEVEL 1
#endif

static const char *AP_SSID = "RADCLOFPV_676767";
static const char *AP_PASS = "";  // open network

static IPAddress AP_IP(192, 168, 0, 1);
static IPAddress AP_GW(192, 168, 0, 1);
static IPAddress AP_MASK(255, 255, 255, 0);

static const uint16_t UDP_PORTS[] = {40000, 50000};
static const uint16_t TCP_PORTS[] = {7060, 8060, 9060};

static WiFiUDP udp40000;
static WiFiUDP udp50000;

struct UdpSrcFlow {
  bool active = false;
  uint16_t src_port = 0;  // local source port to use when sending to phone
  WiFiUDP udp;
};

static const int MAX_UDP_SRC_FLOWS = 8;
static UdpSrcFlow udp_src_flows[MAX_UDP_SRC_FLOWS];

static WiFiServer srv7060(7060);
static WiFiServer srv8060(8060);
static WiFiServer srv9060(9060);

struct TcpSlot {
  bool active = false;
  uint16_t conn_id = 0;
  uint16_t port = 0;
  WiFiClient client;
  bool upstream_ok = false;  // whether STA successfully opened a corresponding outbound connection
};

static const int MAX_TCP_SLOTS = 6;
static TcpSlot tcp_slots[MAX_TCP_SLOTS];
// next_conn_id was used when we used ephemeral per-connection IDs. We now use
// stable conn_id = listening port, so keep no counter.

static SfDecoder dec;
static uint8_t rx_payload[2048];

static IPAddress last_phone_ip(0, 0, 0, 0);

static uint32_t udp_rx_phone_40000 = 0;
static uint32_t udp_rx_phone_50000 = 0;
static uint32_t udp_tx_phone_40000 = 0;
static uint32_t udp_tx_phone_50000 = 0;
static uint32_t tcp_accepts = 0;
static uint32_t tcp_rx_bytes = 0;
static uint32_t tcp_tx_bytes = 0;

static void sf_log(const char *msg) {
#if AP_LOG_LEVEL == 0
  (void)msg;
  return;
#else
  if (!msg) return;
  sf_send(Serial, SF_LOG, 0, 0, (const uint8_t *)msg, (uint16_t)strlen(msg));
#endif
}

static void sf_logf(const char *fmt, ...) {
#if AP_LOG_LEVEL == 0
  (void)fmt;
  return;
#else
  char buf[256];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  sf_log(buf);
#endif
}

static void hex_head(const uint8_t *p, uint16_t n, char *out, size_t out_cap) {
  if (!out || out_cap == 0) return;
  size_t k = 0;
  uint16_t lim = n;
  if (lim > 16) lim = 16;
  for (uint16_t i = 0; i < lim; i++) {
    if (k + 3 >= out_cap) break;
    uint8_t b = p[i];
    static const char *hex = "0123456789abcdef";
    out[k++] = hex[(b >> 4) & 0xF];
    out[k++] = hex[b & 0xF];
    out[k++] = (i + 1 == lim) ? '\0' : ' ';
  }
  if (k == 0) out[0] = '\0';
}

static void on_wifi_event(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_AP_START:
      sf_log("wifi: AP_START");
      break;
    case ARDUINO_EVENT_WIFI_AP_STOP:
      sf_log("wifi: AP_STOP");
      break;
    case ARDUINO_EVENT_WIFI_AP_STACONNECTED: {
      const uint8_t *m = info.wifi_ap_staconnected.mac;
      char mac[32];
      snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
      sf_logf("wifi: STA_CONNECTED mac=%s aid=%u stations=%u", mac,
              (unsigned)info.wifi_ap_staconnected.aid,
              (unsigned)WiFi.softAPgetStationNum());
      break;
    }
    case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED: {
      const uint8_t *m = info.wifi_ap_stadisconnected.mac;
      char mac[32];
      snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
      sf_logf("wifi: STA_DISCONNECTED mac=%s aid=%u stations=%u", mac,
              (unsigned)info.wifi_ap_stadisconnected.aid,
              (unsigned)WiFi.softAPgetStationNum());
      break;
    }
    default:
      break;
  }
}

static TcpSlot *alloc_slot(uint16_t conn_id, uint16_t port, WiFiClient c) {
  for (int i = 0; i < MAX_TCP_SLOTS; i++) {
    if (!tcp_slots[i].active) {
      tcp_slots[i].active = true;
      tcp_slots[i].conn_id = conn_id;
      tcp_slots[i].port = port;
      tcp_slots[i].client = c;
      tcp_slots[i].client.setNoDelay(true);
      tcp_slots[i].upstream_ok = false;
      return &tcp_slots[i];
    }
  }
  return nullptr;
}

static TcpSlot *find_slot_by_port(uint16_t port) {
  for (int i = 0; i < MAX_TCP_SLOTS; i++) {
    if (tcp_slots[i].active && tcp_slots[i].port == port) return &tcp_slots[i];
  }
  return nullptr;
}

static TcpSlot *find_slot(uint16_t conn_id, uint16_t port) {
  for (int i = 0; i < MAX_TCP_SLOTS; i++) {
    if (tcp_slots[i].active && tcp_slots[i].conn_id == conn_id && tcp_slots[i].port == port) return &tcp_slots[i];
  }
  return nullptr;
}

static void free_slot(TcpSlot *s) {
  if (!s) return;
  if (s->client) s->client.stop();
  s->active = false;
  s->conn_id = 0;
  s->port = 0;
  s->upstream_ok = false;
}

static void send_hello() {
  const char *who = "AP";
  sf_send(Serial, SF_HELLO, 0, 0, (const uint8_t *)who, (uint16_t)strlen(who));
}

static void setup_wifi_ap() {
  WiFi.mode(WIFI_AP);
  WiFi.onEvent(on_wifi_event);
  WiFi.softAPConfig(AP_IP, AP_GW, AP_MASK);
  if (AP_PASS && AP_PASS[0]) WiFi.softAP(AP_SSID, AP_PASS);
  else WiFi.softAP(AP_SSID);
  sf_logf("AP up: ssid=%s ip=%s", AP_SSID, WiFi.softAPIP().toString().c_str());
}

static void setup_listeners() {
  udp40000.begin(40000);
  udp50000.begin(50000);

  srv7060.begin();
  srv8060.begin();
  srv9060.begin();
}

static void poll_udp(WiFiUDP &u, uint16_t local_port) {
  int n = u.parsePacket();
  if (n <= 0) return;
  if (n > (int)sizeof(rx_payload)) n = (int)sizeof(rx_payload);
  int r = u.read(rx_payload, n);
  if (r <= 0) return;

  IPAddress rip = u.remoteIP();
  last_phone_ip = rip;
  uint16_t src_port = (uint16_t)u.remotePort();

  if (local_port == 40000) udp_rx_phone_40000++;
  else if (local_port == 50000) udp_rx_phone_50000++;

#if AP_LOG_LEVEL >= 2
  // Log a small sample of packet heads for debugging. This is intentionally noisy.
  static uint32_t udp_log_count = 0;
  if (udp_log_count < 20) {
    udp_log_count++;
    char head[64];
    hex_head(rx_payload, (uint16_t)r, head, sizeof(head));
    sf_logf("udp: rx from=%s:%u -> %u len=%d head=%s",
            rip.toString().c_str(), (unsigned)src_port, (unsigned)local_port, r, head);
  }
#else
  // Even at low log level, log the first packet per port so we can confirm the app is talking.
  static bool first_40000 = true;
  static bool first_50000 = true;
  if ((local_port == 40000 && first_40000) || (local_port == 50000 && first_50000)) {
    if (local_port == 40000) first_40000 = false;
    if (local_port == 50000) first_50000 = false;
    sf_logf("udp: first_rx from=%s:%u -> %u len=%d",
            rip.toString().c_str(), (unsigned)src_port, (unsigned)local_port, r);
  }
#endif

  // Frame uses:
  //   conn_id = UDP source port (phone)
  //   port    = UDP destination port (40000/50000)
  sf_send(Serial, SF_UDP, src_port, local_port, rx_payload, (uint16_t)r);
}

static UdpSrcFlow *find_udp_src(uint16_t src_port) {
  for (int i = 0; i < MAX_UDP_SRC_FLOWS; i++) {
    if (udp_src_flows[i].active && udp_src_flows[i].src_port == src_port) return &udp_src_flows[i];
  }
  return nullptr;
}

static UdpSrcFlow *ensure_udp_src(uint16_t src_port) {
  if (src_port == 40000 || src_port == 50000) return nullptr;  // handled by dedicated sockets
  UdpSrcFlow *f = find_udp_src(src_port);
  if (f) return f;
  for (int i = 0; i < MAX_UDP_SRC_FLOWS; i++) {
    if (!udp_src_flows[i].active) {
      udp_src_flows[i].active = true;
      udp_src_flows[i].src_port = src_port;
      bool ok = udp_src_flows[i].udp.begin(src_port);
      sf_logf("udp: bind src_port=%u ok=%u", (unsigned)src_port, (unsigned)(ok ? 1 : 0));
      return &udp_src_flows[i];
    }
  }
  sf_logf("udp: bind_fail src_port=%u", (unsigned)src_port);
  return nullptr;
}

static void accept_tcp(WiFiServer &srv, uint16_t port) {
  WiFiClient c = srv.available();
  if (!c) return;

  // Keep at most one phone TCP connection per port. The app retries aggressively when
  // the drone-side connect fails; letting many pile up increases jitter.
  TcpSlot *existing = find_slot_by_port(port);
  if (existing) {
    sf_logf("tcp: replace port=%u old_conn=%u", (unsigned)port, (unsigned)existing->conn_id);
    // Only replace the phone-side socket. Keep the STA/drone-side connection alive;
    // otherwise app reconnects will thrash the upstream and never settle.
    free_slot(existing);
  }

  last_phone_ip = c.remoteIP();
  // IMPORTANT: use a stable conn_id per listening port.
  // The app will reconnect frequently while the upstream (drone-side) isn't ready.
  // If we key conn_id off the phone's ephemeral source port, the STA will churn
  // outbound connections and never settle. Using conn_id=port keeps state stable.
  uint16_t conn_id = port;
  TcpSlot *slot = alloc_slot(conn_id, port, c);
  if (!slot) {
    c.stop();
    return;
  }
  tcp_accepts++;
  sf_logf("tcp: accept port=%u from=%s:%u conn=%u",
          (unsigned)port,
          c.remoteIP().toString().c_str(),
          (unsigned)c.remotePort(),
          (unsigned)slot->conn_id);
  sf_send(Serial, SF_TCP_OPEN, slot->conn_id, slot->port, nullptr, 0);
}

static void poll_tcp_slots() {
  for (int i = 0; i < MAX_TCP_SLOTS; i++) {
    TcpSlot *s = &tcp_slots[i];
    if (!s->active) continue;

    if (!s->client.connected()) {
      sf_send(Serial, SF_TCP_CLOSE, s->conn_id, s->port, nullptr, 0);
      free_slot(s);
      continue;
    }

    int avail = s->client.available();
    if (avail <= 0) continue;
    while (avail > 0) {
      int to_read = avail;
      if (to_read > (int)sizeof(rx_payload)) to_read = (int)sizeof(rx_payload);
      int r = s->client.read(rx_payload, to_read);
      if (r <= 0) break;
      tcp_rx_bytes += (uint32_t)r;
#if AP_LOG_LEVEL >= 2
      static uint16_t first_logged_conn = 0;
      if (first_logged_conn != s->conn_id) {
        first_logged_conn = s->conn_id;
        char head[64];
        hex_head(rx_payload, (uint16_t)r, head, sizeof(head));
        sf_logf("tcp: rx conn=%u port=%u len=%d head=%s",
                (unsigned)s->conn_id, (unsigned)s->port, r, head);
      }
#endif
      sf_send(Serial, SF_TCP_DATA, s->conn_id, s->port, rx_payload, (uint16_t)r);
      avail = s->client.available();
    }
  }
}

static void handle_serial_frame(const SfHeader &h, const uint8_t *payload, uint16_t paylen) {
  if (h.type == SF_UDP) {
    // Inbound from drone-side: send to phone.
    // Fields:
    //   conn_id = UDP destination port at phone (original phone src port)
    //   port    = UDP source port to use (e.g. 40000/50000/7070/etc)
    if (!last_phone_ip) return;

    WiFiUDP *u = nullptr;
    if (h.port == 40000) u = &udp40000;
    else if (h.port == 50000) u = &udp50000;
    else {
      UdpSrcFlow *f = ensure_udp_src(h.port);
      if (f) u = &f->udp;
    }
    if (!u) return;

    uint16_t phone_port = h.conn;
    u->beginPacket(last_phone_ip, phone_port);
    if (paylen && payload) u->write(payload, paylen);
    u->endPacket();

    if (h.port == 40000) udp_tx_phone_40000++;
    else if (h.port == 50000) udp_tx_phone_50000++;

#if AP_LOG_LEVEL >= 2
    static uint32_t tx_log_count = 0;
    if (tx_log_count < 20) {
      tx_log_count++;
      char head[64];
      hex_head(payload, paylen, head, sizeof(head));
      sf_logf("udp: tx to=%s:%u src=%u len=%u head=%s",
              last_phone_ip.toString().c_str(),
              (unsigned)phone_port,
              (unsigned)h.port,
              (unsigned)paylen,
              head);
    }
#else
    static bool first_tx_40000 = true;
    static bool first_tx_50000 = true;
    static uint16_t first_tx_other = 0;
    if ((h.port == 40000 && first_tx_40000) || (h.port == 50000 && first_tx_50000)) {
      if (h.port == 40000) first_tx_40000 = false;
      if (h.port == 50000) first_tx_50000 = false;
      sf_logf("udp: first_tx to=%s:%u src=%u len=%u",
              last_phone_ip.toString().c_str(),
              (unsigned)phone_port,
              (unsigned)h.port,
              (unsigned)paylen);
    } else if (h.port != 40000 && h.port != 50000 && first_tx_other == 0) {
      // This is the path for e.g. drone video packets from src port 7070.
      first_tx_other = h.port;
      sf_logf("udp: first_tx_other to=%s:%u src=%u len=%u",
              last_phone_ip.toString().c_str(),
              (unsigned)phone_port,
              (unsigned)h.port,
              (unsigned)paylen);
    }
#endif
    return;
  }

  if (h.type == SF_TCP_OPEN_OK) {
    TcpSlot *s = find_slot(h.conn, h.port);
    if (s) s->upstream_ok = true;
    sf_logf("tcp: open_ok conn=%u port=%u", (unsigned)h.conn, (unsigned)h.port);
    return;
  }

  if (h.type == SF_TCP_DATA) {
    TcpSlot *s = find_slot(h.conn, h.port);
    if (!s) return;
    if (!s->client.connected()) return;
    if (paylen && payload) s->client.write(payload, paylen);
    tcp_tx_bytes += (uint32_t)paylen;
    return;
  }

  if (h.type == SF_TCP_CLOSE) {
    TcpSlot *s = find_slot(h.conn, h.port);
    if (!s) return;
    sf_logf("tcp: close conn=%u port=%u", (unsigned)h.conn, (unsigned)h.port);
    free_slot(s);
    return;
  }

  if (h.type == SF_TCP_OPEN_FAIL) {
    // Drone-side couldn't open. DO NOT drop the phone TCP connection: the app will
    // otherwise thrash reconnects and may never progress to sending UDP controls.
    TcpSlot *s = find_slot(h.conn, h.port);
    if (!s) return;
    s->upstream_ok = false;
    sf_logf("tcp: open_fail conn=%u port=%u (keeping phone tcp open)", (unsigned)h.conn, (unsigned)h.port);
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

void setup() {
  Serial.begin(921600);
  delay(200);

  setup_wifi_ap();
  setup_listeners();

  send_hello();
}

void loop() {
  static uint32_t last_hello_ms = 0;
  uint32_t now = millis();
  if (now - last_hello_ms > 2000) {
    last_hello_ms = now;
    send_hello();
  }
#if AP_LOG_LEVEL >= 2
  static uint32_t last_stats_ms = 0;
  if (now - last_stats_ms > 5000) {
    last_stats_ms = now;
    sf_logf("stats: stations=%u phone_ip=%s udp_rx=%lu/%lu udp_tx=%lu/%lu tcp_accepts=%lu tcp_rxB=%lu tcp_txB=%lu",
            (unsigned)WiFi.softAPgetStationNum(),
            last_phone_ip.toString().c_str(),
            (unsigned long)udp_rx_phone_40000, (unsigned long)udp_rx_phone_50000,
            (unsigned long)udp_tx_phone_40000, (unsigned long)udp_tx_phone_50000,
            (unsigned long)tcp_accepts,
            (unsigned long)tcp_rx_bytes,
            (unsigned long)tcp_tx_bytes);
  }
#endif

  poll_udp(udp40000, 40000);
  poll_udp(udp50000, 50000);

  accept_tcp(srv7060, 7060);
  accept_tcp(srv8060, 8060);
  accept_tcp(srv9060, 9060);
  poll_tcp_slots();

  poll_serial();
  delay(1);
}
