#include <WiFi.h>
#include <WiFiClientSecure.h>

// ----------- USER SETTINGS -----------
const char *WIFI_SSID = "Pixel_3498";
const char *WIFI_PASSWORD = "pikachuu";

const char *HOST = "example.com"; // no https://
const uint16_t PORT = 443;
const char *PATH = "/key";

const unsigned long SEND_PERIOD_MS = 5000;

// Example AES key (replace with yours)
const char *AES_KEY = "0123456789ABCDEF0123456789ABCDEF";
// ------------------------------------

#define CLK_PIN 4
#define CUSTOM_PIN 5

unsigned long lastSend = 0;

bool postKeyTLS()
{
    WiFiClientSecure client;

    // For testing only — use real certificate in production
    client.setInsecure();

    if (!client.connect(HOST, PORT))
    {
        Serial.println("TLS connect failed");
        return false;
    }

    String body = String(AES_KEY) + "\n";

    client.println(String("POST ") + PATH + " HTTP/1.1");
    client.println(String("Host: ") + HOST);
    client.println("User-Agent: esp32");
    client.println("Connection: close");
    client.println("Content-Type: text/plain");
    client.print("Content-Length: ");
    client.println(body.length());
    client.println();
    client.println(body);

    client.stop();
    return true;
}

void setup()
{
    Serial.begin(115200);
    delay(200);

    // Custom pin held HIGH
    pinMode(CUSTOM_PIN, OUTPUT);
    digitalWrite(CUSTOM_PIN, HIGH);

    // 40 MHz clock on GPIO14 (Arduino-ESP32 v3 API)
    ledcAttach(CLK_PIN, 40000000, 1);

    // Connect Wi-Fi
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting WiFi");
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(300);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    // Turn off Bluetooth (optional)
    btStop();

    lastSend = millis();
}

void loop()
{
    // 1. Keep WiFi alive
    if (WiFi.status() != WL_CONNECTED)
    {
        WiFi.reconnect();
        delay(200);
        return;
    }

    // 2. Generate Steady Noise (Math Hammer)
    // This burns power constantly, making the voltage sag/ripple easier to see on the FPGA LEDs.
    for (int i = 0; i < 10000; i++)
    {
        volatile int x = i * i;
    }

    // 3. Send Key (The big spike)
    unsigned long now = millis();
    if (now - lastSend >= SEND_PERIOD_MS)
    {
        lastSend = now;

        // FUTURE PROOFING: Pulse the trigger!
        digitalWrite(CUSTOM_PIN, LOW);
        delayMicroseconds(10);
        digitalWrite(CUSTOM_PIN, HIGH); // Trigger rising edge

        if (postKeyTLS())
        {
            Serial.println("Key sent");
            // This will print the frequency in MHz (e.g., 240)
            Serial.print("CPU Frequency: ");
            Serial.print(ESP.getCpuFreqMHz());
            Serial.println(" MHz");
        }
    }
}