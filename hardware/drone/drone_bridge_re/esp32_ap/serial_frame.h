#pragma once

#include <Arduino.h>

// Binary framing for ESP32<->host serial.
//
// Layout (little endian where applicable):
//   magic[2] = 0xD0 0xB0
//   len_u16  = number of bytes from ver..crc16 inclusive
//   ver_u8   = 1
//   type_u8  = message type
//   conn_u16 = connection id (TCP) or UDP src/dst port depending on direction
//   port_u16 = TCP port or UDP dst/src port depending on direction
//   paylen_u16
//   payload[paylen]
//   crc16_u16 = CRC16-CCITT (poly 0x1021, init 0xFFFF) over ver..payload
//
// This is designed so the Python bridge can forward frames without understanding them.

static const uint8_t SF_MAGIC0 = 0xD0;
static const uint8_t SF_MAGIC1 = 0xB0;
static const uint8_t SF_VER = 0x01;

enum SfType : uint8_t {
  SF_HELLO = 0x01,
  SF_LOG = 0x03,
  SF_UDP = 0x02,

  SF_TCP_OPEN = 0x10,
  SF_TCP_OPEN_OK = 0x11,
  SF_TCP_OPEN_FAIL = 0x12,
  SF_TCP_DATA = 0x13,
  SF_TCP_CLOSE = 0x14,
};

static inline uint16_t sf_crc16_ccitt(const uint8_t *data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (int b = 0; b < 8; b++) {
      if (crc & 0x8000) crc = (crc << 1) ^ 0x1021;
      else crc <<= 1;
    }
  }
  return crc;
}

static inline uint16_t sf_crc16_update(uint16_t crc, const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
  }
  return crc;
}

struct SfHeader {
  uint8_t ver;
  uint8_t type;
  uint16_t conn;
  uint16_t port;
  uint16_t paylen;
};

static inline void sf_write_u16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)(v & 0xFF);
  p[1] = (uint8_t)((v >> 8) & 0xFF);
}

static inline uint16_t sf_read_u16(const uint8_t *p) {
  return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static inline bool sf_send(Stream &s, uint8_t type, uint16_t conn, uint16_t port, const uint8_t *payload, uint16_t paylen) {
  // ver..paylen (1+1+2+2+2 = 8)
  const uint16_t hdr_len = 8;
  const uint16_t inner_len = hdr_len + paylen + 2; // +crc16
  uint8_t pre[4 + hdr_len];
  pre[0] = SF_MAGIC0;
  pre[1] = SF_MAGIC1;
  sf_write_u16(&pre[2], inner_len);
  pre[4] = SF_VER;
  pre[5] = type;
  sf_write_u16(&pre[6], conn);
  sf_write_u16(&pre[8], port);
  sf_write_u16(&pre[10], paylen);

  // CRC over ver..payload.
  uint16_t crc_final = 0xFFFF;
  crc_final = sf_crc16_update(crc_final, &pre[4], hdr_len);
  if (paylen && payload) crc_final = sf_crc16_update(crc_final, payload, paylen);

  // Write frame.
  s.write(pre, sizeof(pre));
  if (paylen && payload) s.write(payload, paylen);
  uint8_t crc_le[2];
  sf_write_u16(crc_le, crc_final);
  s.write(crc_le, 2);
  return true;
}

// Incremental decoder for frames from a Stream.
class SfDecoder {
 public:
  static const size_t MAX_FRAME = 4096;

  // Returns true when a complete, CRC-valid frame is available in out_*.
  bool poll(Stream &s, SfHeader &out_h, uint8_t *out_payload, uint16_t out_payload_cap, uint16_t &out_payload_len) {
    while (s.available()) {
      uint8_t b = (uint8_t)s.read();
      if (_buf_len < sizeof(_buf)) _buf[_buf_len++] = b;
      else {
        // Buffer overflow; resync.
        _buf_len = 0;
      }

      // Resync on magic.
      if (_buf_len >= 2) {
        // If first byte isn't magic, shift until it is.
        while (_buf_len >= 1 && _buf[0] != SF_MAGIC0) {
          memmove(_buf, _buf + 1, _buf_len - 1);
          _buf_len--;
        }
        if (_buf_len >= 2 && _buf[1] != SF_MAGIC1) {
          // Keep SF_MAGIC0 as potential start.
          if (_buf[1] == SF_MAGIC0) {
            _buf[0] = SF_MAGIC0;
            _buf_len = 1;
          } else {
            _buf_len = 0;
          }
        }
      }

      if (_buf_len < 4) continue;
      if (_buf[0] != SF_MAGIC0 || _buf[1] != SF_MAGIC1) continue;
      uint16_t inner_len = sf_read_u16(&_buf[2]);
      if (inner_len < 10 || inner_len > MAX_FRAME) {  // minimum ver..crc16 (8+0+2)
        _buf_len = 0;
        continue;
      }
      const uint16_t total_len = 4 + inner_len;
      if (_buf_len < total_len) continue;

      // Parse.
      const uint8_t *p = &_buf[4];
      SfHeader h;
      h.ver = p[0];
      h.type = p[1];
      h.conn = sf_read_u16(&p[2]);
      h.port = sf_read_u16(&p[4]);
      h.paylen = sf_read_u16(&p[6]);
      if (h.ver != SF_VER) {
        _buf_len = 0;
        continue;
      }
      if ((uint32_t)h.paylen + 8 + 2 != inner_len) {
        _buf_len = 0;
        continue;
      }

      const uint8_t *payload = &_buf[4 + 8];
      uint16_t want_crc = sf_read_u16(&_buf[4 + 8 + h.paylen]);

      // CRC over ver..payload.
      uint16_t crc = 0xFFFF;
      for (int i = 0; i < 8; i++) {
        crc ^= (uint16_t)p[i] << 8;
        for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
      }
      for (uint16_t i = 0; i < h.paylen; i++) {
        crc ^= (uint16_t)payload[i] << 8;
        for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
      }
      if (crc != want_crc) {
        // Drop one byte and continue resync; don't nuke buffer completely.
        memmove(_buf, _buf + 1, _buf_len - 1);
        _buf_len--;
        continue;
      }

      // Copy payload out.
      out_payload_len = h.paylen;
      if (out_payload_len > out_payload_cap) out_payload_len = out_payload_cap;
      if (out_payload_len && out_payload) memcpy(out_payload, payload, out_payload_len);
      out_h = h;

      // Consume this frame.
      const size_t remain = _buf_len - total_len;
      if (remain) memmove(_buf, _buf + total_len, remain);
      _buf_len = remain;
      return true;
    }
    return false;
  }

 private:
  uint8_t _buf[MAX_FRAME + 8];
  size_t _buf_len = 0;
};
