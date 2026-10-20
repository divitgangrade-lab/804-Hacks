// =====================================================================
// WETBULB RACK  ·  Arduino Uno R3  ·  804 Hacks 2026
// DHT11 (air) + 8x2 LCD (screens) + fan via ULN2003 (cooling tower) + joystick
// =====================================================================
// The fan is the data center's cooling tower: the more water it would
// evaporate (higher wet-bulb), the faster it spins.
//
// Without the dashboard: works on its own (fan follows the live air).
// With the dashboard:    the dashboard decides, the joystick controls it.
//
// Messages (115200 baud, one per line):
//   Arduino -> app:  S,<tempC>,<humidity>         every 2 s
//                    J,PAGE,<0-5>                 joystick left/right
//                    J,W,<0-100>                  joystick up/down (carbon weight %)
//                    J,BTN                        joystick click
//   app -> Arduino:  L,<line1>,<line2>,<fan 0-255>,<co2 g/kWh>,<carbon weight %>
//                    icons inside line1/line2:  ~ drop  ^ cloud  ! thermometer
//                                               * fan (spins)  # full block  _ empty block
//
// Libraries (Tools -> Manage Libraries): "DHT sensor library" by Adafruit
// (click "Install all" for Adafruit Unified Sensor). LiquidCrystal + EEPROM are built in.
// =====================================================================

#include <LiquidCrystal.h>
#include <DHT.h>
#include <EEPROM.h>

// ---------- pins ----------
const byte PIN_DHT      = 7;
const byte PIN_FAN      = 9;    // PWM -> ULN2003 IN1
const byte PIN_CONTRAST = 6;    // PWM -> LCD pin 3 (V0)
const byte PIN_JOY_X    = A0;
const byte PIN_JOY_Y    = A1;
const byte PIN_JOY_BTN  = A2;

// ---------- tune these if needed ----------
const int  DEFAULT_CONTRAST = 50;  // lower = darker text (hold joystick button + up/down to adjust live)
const int  MIN_RUN_PWM = 90;       // lowest PWM where your fan still turns (raise if it only hums)
const bool SWAP_XY = false;        // joystick mounted sideways? -> true
const bool FLIP_X  = false;        // left/right backwards? -> true
const bool FLIP_Y  = false;        // up/down backwards? -> true

LiquidCrystal lcd(12, 11, 5, 4, 3, 2);   // RS, E, D4, D5, D6, D7
DHT dht(PIN_DHT, DHT11);

// ---------- custom icons (LCD codes 8-15 = custom slots 0-7) ----------
const uint8_t G_DROP = 8, G_CLOUD = 9, G_THERM = 10, G_FAN1 = 11,
              G_FAN2 = 12, G_FULL = 13, G_EMPTY = 14, G_KNOB = 15;
byte iconDrop[8]  = {0b00100, 0b00100, 0b01010, 0b01010, 0b10001, 0b10001, 0b01110, 0b00000};
byte iconCloud[8] = {0b00000, 0b01100, 0b10010, 0b10001, 0b10001, 0b11111, 0b00000, 0b00000};
byte iconTherm[8] = {0b00100, 0b01010, 0b01010, 0b01110, 0b01110, 0b11111, 0b11111, 0b01110};
byte iconFan1[8]  = {0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000, 0b00000};
byte iconFan2[8]  = {0b00000, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b00000, 0b00000};
byte iconFull[8]  = {0b00000, 0b11111, 0b11111, 0b11111, 0b11111, 0b11111, 0b11111, 0b00000};
byte iconEmpty[8] = {0b00000, 0b11111, 0b10001, 0b10001, 0b10001, 0b10001, 0b11111, 0b00000};
byte iconKnob[8]  = {0b00100, 0b01110, 0b11111, 0b11111, 0b11111, 0b01110, 0b00100, 0b00000};

// ---------- pages ----------
enum { P_STATUS, P_AIR, P_WETBULB, P_WATER, P_CO2, P_FOCUS, N_PAGES };
const char *TITLES[N_PAGES] = {"<STATUS>", "<  AIR >", "<WETBLB>", "<WATER >", "<  CO2 >", "<FOCUS >"};

// ---------- state ----------
float tempC = NAN, humid = NAN, twb = NAN, water = 0;
bool haveReading = false, sensorError = false;
bool linked = false;
char appL1[9] = "", appL2[9] = "";
int appCO2 = -1;
int carbonWeight = 50;            // 0 = only water matters, 100 = only carbon matters
int fanSpeed = 0;
int contrast = DEFAULT_CONTRAST;
byte page = P_STATUS;
bool animTick = false;

unsigned long lastRead = 0, lastMsg = 0, lastAnim = 0, lastJoy = 0, lastInput = 0;
unsigned long overlayUntil = 0, nextRepeat = 0;
char overlay1[9], overlay2[9];

char serialBuf[64];
byte serialLen = 0;

uint8_t frame[2][8];
uint8_t onLcd[2][8];

// =====================================================================
// physics (same model as the dashboard)
// =====================================================================
float wetBulb(float t, float rh) {          // Stull (2011)
  return t * atan(0.151977 * sqrt(rh + 8.313659)) + atan(t + rh) - atan(rh - 1.676331)
         + 0.00391838 * pow(rh, 1.5) * atan(0.023101 * rh) - 4.686035;
}
float coolingWater(float wb) {              // L per kWh, free cooling below 10 C wet-bulb
  return constrain(0.15 * (wb - 10.0), 0.0, 3.0);
}
int fanForWater(float litersPerKwh) {        // proportional control
  if (litersPerKwh <= 0.0) return 0;
  return MIN_RUN_PWM + (int)((255 - MIN_RUN_PWM) * litersPerKwh / 3.0);
}

// =====================================================================
// output helpers
// =====================================================================
void setFan(int speed) {
  speed = constrain(speed, 0, 255);
  if (speed > 0 && speed < MIN_RUN_PWM) speed = MIN_RUN_PWM;
  if (speed > 0 && fanSpeed == 0) {          // kick-start small motors
    analogWrite(PIN_FAN, 255);
    delay(120);
  }
  analogWrite(PIN_FAN, speed);
  fanSpeed = speed;
}

void setLine(byte row, const char *s) {
  for (byte i = 0; i < 8; i++) frame[row][i] = ' ';
  for (byte i = 0; i < 8 && s[i]; i++) frame[row][i] = (uint8_t)s[i];
}

uint8_t translate(uint8_t c) {
  switch (c) {
    case '~': return G_DROP;
    case '^': return G_CLOUD;
    case '!': return G_THERM;
    case '#': return G_FULL;
    case '_': return G_EMPTY;
    case '*': return (fanSpeed > 0 && animTick) ? G_FAN2 : G_FAN1;
    default:  return c;
  }
}

void flush() {                               // only redraw cells that changed: no flicker
  for (byte r = 0; r < 2; r++)
    for (byte c = 0; c < 8; c++) {
      uint8_t ch = translate(frame[r][c]);
      if (ch != onLcd[r][c]) {
        lcd.setCursor(c, r);
        lcd.write(ch);
        onLcd[r][c] = ch;
      }
    }
}

void bar(char *out, float v, float lo, float hi) {   // 8-cell bar graph
  int n = (int)((v - lo) / (hi - lo) * 8.0 + 0.5);
  n = constrain(n, 0, 8);
  for (byte i = 0; i < 8; i++) out[i] = (i < n) ? '#' : '_';
  out[8] = '\0';
}

void showOverlay(const char *a, const char *b, unsigned int ms) {
  strncpy(overlay1, a, 8); overlay1[8] = '\0';
  strncpy(overlay2, b, 8); overlay2[8] = '\0';
  overlayUntil = millis() + ms;
}

void showTitle() {
  char dots[9] = "        ";
  for (byte i = 0; i < N_PAGES; i++) dots[1 + i] = (i == page) ? '#' : '.';
  showOverlay(TITLES[page], dots, 650);
}

// =====================================================================
// pages
// =====================================================================
void renderPage() {
  char a[9] = "", b[9] = "", num[10];

  if (millis() < overlayUntil) {
    setLine(0, overlay1); setLine(1, overlay2);
    return;
  }

  switch (page) {
    case P_STATUS:
      if (linked) {
        strcpy(a, appL1); strcpy(b, appL2);
      } else if (sensorError) {
        strcpy(a, "SENSOR?"); strcpy(b, "CHECK D7");
      } else if (!haveReading) {
        strcpy(a, "~WETBULB"); strcpy(b, "READING.");
      } else {
        strcpy(a, water > 0 ? "*COOLING" : "~FREEAIR");
        dtostrf(water, 1, 1, num);
        snprintf(b, 9, "H2O %sL", num);
      }
      break;

    case P_AIR:
      if (!haveReading) { strcpy(a, "!  --.-C"); strcpy(b, "~  --% "); break; }
      dtostrf(tempC, 1, 1, num);
      snprintf(a, 9, "! %sC", num);
      snprintf(b, 9, "~ %d%% RH", (int)humid);
      break;

    case P_WETBULB:
      if (!haveReading) { strcpy(a, "WB --.-C"); bar(b, 0, 0, 1); break; }
      dtostrf(twb, 1, 1, num);
      snprintf(a, 9, "WB %sC", num);
      bar(b, twb, 0, 30);
      break;

    case P_WATER:
      dtostrf(water, 1, 2, num);
      snprintf(a, 9, "~%s L", num);
      bar(b, water, 0, 3);
      break;

    case P_CO2:
      if (appCO2 < 0) { strcpy(a, "^CO2 ---"); strcpy(b, "NEED APP"); break; }
      snprintf(a, 9, "^%d g", appCO2);
      bar(b, appCO2, 200, 550);
      break;

    case P_FOCUS: {
      strcpy(a, "^CO2 H2O");
      for (byte i = 0; i < 8; i++) b[i] = '-';
      byte pos = (byte)((100 - carbonWeight) * 7L / 100);
      b[pos] = (char)G_KNOB;
      b[8] = '\0';
      break;
    }
  }
  setLine(0, a);
  setLine(1, b);
}

// =====================================================================
// joystick
// =====================================================================
void changePage(int delta) {
  page = (page + N_PAGES + delta) % N_PAGES;
  Serial.print("J,PAGE,"); Serial.println(page);
  showTitle();
}

void changeWeight(int delta) {
  carbonWeight = constrain(carbonWeight + delta, 0, 100);
  Serial.print("J,W,"); Serial.println(carbonWeight);
  page = P_FOCUS;
  overlayUntil = 0;
}

void changeContrast(int delta) {
  contrast = constrain(contrast + delta, 0, 150);
  analogWrite(PIN_CONTRAST, contrast);
  EEPROM.update(0, (byte)contrast);
  char b[9];
  bar(b, contrast, 0, 150);
  showOverlay("CONTRAST", b, 1200);
}

void readJoystick() {
  static char lastDir = 0;
  static bool btnDown = false, adjusted = false;
  static unsigned long btnChanged = 0;

  int x = analogRead(PIN_JOY_X), y = analogRead(PIN_JOY_Y);
  if (SWAP_XY) { int s = x; x = y; y = s; }
  if (FLIP_X) x = 1023 - x;
  if (FLIP_Y) y = 1023 - y;

  char dir = 0;
  if (x < 250) dir = 'L';
  else if (x > 770) dir = 'R';
  else if (y < 250) dir = 'U';
  else if (y > 770) dir = 'D';

  bool pressed = digitalRead(PIN_JOY_BTN) == LOW;
  unsigned long now = millis();
  if (pressed != btnDown && now - btnChanged > 30) {
    btnChanged = now;
    btnDown = pressed;
    if (pressed) adjusted = false;
    else if (!adjusted) {                    // a plain click
      Serial.println("J,BTN");
      if (linked) showOverlay("*REPLAY", "  > GO", 900);
      else        showOverlay("NO APP", "CONNECT", 900);
    }
    lastInput = now;
  }

  bool fresh = dir != lastDir;
  bool repeat = dir && !fresh && now >= nextRepeat && (dir == 'U' || dir == 'D');
  if (dir && (fresh || repeat)) {
    nextRepeat = now + (fresh ? 400 : 180);
    lastInput = now;
    if (btnDown && (dir == 'U' || dir == 'D')) {   // hold click + up/down = contrast
      adjusted = true;
      changeContrast(dir == 'U' ? -5 : 5);
    } else if (dir == 'L') changePage(-1);
    else if (dir == 'R') changePage(1);
    else if (dir == 'U') changeWeight(-10);        // up = care more about water
    else if (dir == 'D') changeWeight(10);         // down = care more about carbon
  }
  lastDir = dir;
}

// =====================================================================
// serial from the dashboard
// =====================================================================
void handleLine(char *line) {
  if (line[0] != 'L' || line[1] != ',') return;
  char *f[6];
  byte n = 0;
  char *p = line + 2;
  f[n++] = p;
  while (*p && n < 6) {
    if (*p == ',') { *p = '\0'; f[n++] = p + 1; }
    p++;
  }
  strncpy(appL1, f[0], 8); appL1[8] = '\0';
  if (n > 1) { strncpy(appL2, f[1], 8); appL2[8] = '\0'; }
  if (n > 2) setFan(atoi(f[2]));
  if (n > 3) appCO2 = atoi(f[3]);
  if (n > 4) carbonWeight = constrain(atoi(f[4]), 0, 100);
  linked = true;
  lastMsg = millis();
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialLen > 0) {
        serialBuf[serialLen] = '\0';
        handleLine(serialBuf);
        serialLen = 0;
      }
    } else if (serialLen < sizeof(serialBuf) - 1) {
      serialBuf[serialLen++] = c;
    }
  }
}

// =====================================================================
// setup + loop
// =====================================================================
void setup() {
  Serial.begin(115200);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_CONTRAST, OUTPUT);
  pinMode(PIN_JOY_BTN, INPUT_PULLUP);

  byte saved = EEPROM.read(0);
  contrast = (saved <= 150) ? saved : DEFAULT_CONTRAST;
  analogWrite(PIN_CONTRAST, contrast);

  lcd.begin(8, 2);
  lcd.createChar(0, iconDrop);
  lcd.createChar(1, iconCloud);
  lcd.createChar(2, iconTherm);
  lcd.createChar(3, iconFan1);
  lcd.createChar(4, iconFan2);
  lcd.createChar(5, iconFull);
  lcd.createChar(6, iconEmpty);
  lcd.createChar(7, iconKnob);
  lcd.clear();
  memset(onLcd, 0xFF, sizeof(onLcd));
  dht.begin();

  // boot animation + fan self-test
  setLine(0, "~WETBULB");
  setFan(200);
  for (byte i = 0; i <= 8; i++) {
    char b[9];
    bar(b, i, 0, 8);
    setLine(1, b);
    animTick = !animTick;
    flush();
    delay(150);
  }
  setFan(0);
  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();

  // 1. air reading every 2 s
  if (now - lastRead >= 2000) {
    lastRead = now;
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (isnan(h) || isnan(t)) {
      sensorError = true;
      Serial.println("E,dht");
    } else {
      sensorError = false;
      haveReading = true;
      tempC = t; humid = h;
      twb = wetBulb(t, h);
      water = coolingWater(twb);
      Serial.print("S,"); Serial.print(t, 1); Serial.print(","); Serial.println(h, 0);
      if (!linked) setFan(fanForWater(water));       // standalone proportional control
    }
  }

  // 2. inputs
  readSerial();
  if (now - lastJoy >= 20) { lastJoy = now; readJoystick(); }

  // 3. dashboard went quiet -> standalone mode
  if (linked && now - lastMsg > 15000) {
    linked = false;
    showOverlay("NO LINK", "SOLO MOD", 1500);
  }

  // 4. go back to the status page after 30 s without touching the joystick
  if (page != P_STATUS && now - lastInput > 30000) page = P_STATUS;

  // 5. animate + draw 4x per second
  if (now - lastAnim >= 250) {
    lastAnim = now;
    animTick = !animTick;
  }
  renderPage();
  flush();
}
