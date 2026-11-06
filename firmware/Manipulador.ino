#define BLYNK_TEMPLATE_ID "TMPL24p6M39YQ"
#define BLYNK_TEMPLATE_NAME "Manipulador Robotico"
#include "secrets.h"

#include <WiFi.h>
#include <WiFiMulti.h>
#include <BlynkSimpleEsp32.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <Preferences.h>
#include <math.h>

WiFiMulti redes;
Adafruit_PWMServoDriver pca(0x40);
Preferences memoria;

const int TRIG = 25, ECHO = 33;
const int canales[6] = {10, 11, 12, 13, 14, 15};
const float minimo[6] = {5, 15, 0, 10, 25, 20};
const float maximo[6] = {80, 93, 80, 78, 70, 85};

// Posiciones originales: 50% en cada servo = postura de referencia.
float actual[6] = {50, 50, 50, 50, 50, 50};
float destino[6] = {50, 50, 50, 50, 50, 50};
float pinzaAbierta = 110.0f * 100.0f / 180.0f;
float pinzaCerrada = 65.0f * 100.0f / 180.0f;
int velocidad = 30;
int rutinaElegida = 1;
bool iniciado = false;
bool detenido = false;
bool rutinaActiva = false;
unsigned long ultimoPaso = 0, ultimoPC = 0, ultimoDist = 0;
const unsigned long VIGILANCIA_MS = 4000;

// Blynk corre en el otro nucleo para no detener los pulsos al reconectar WiFi.
// Sus botones dejan pedidos; solo el loop modifica los destinos de los servos.
portMUX_TYPE candado = portMUX_INITIALIZER_UNLOCKED;
struct Pedidos {
  bool stop = false, resume = false, iniciar = false, sync = false;
  bool servo[6] = {false, false, false, false, false, false};
  float pct[6] = {0};
  bool abrir = false, cerrar = false;
  int guardar = 0;                  // V17: abierta; V18: cerrada
  bool cambiarVelocidad = false;
  int nuevaVelocidad = 30;
  int numeroRutina = 1;
} pedidos;

struct Publicaciones {
  bool estado = false, xyz = false, sliders = false;
  bool stop = false, velocidad = false, distancia = false;
  char texto[48] = "";
  float x = 0, y = 0, z = 0, dist = -1;
  float porcentajes[6] = {0};
  bool detenido = false;
  int vel = 30;
} pendientes;

float aOriginal(int i, float pct) {
  return minimo[i] + pct * (maximo[i] - minimo[i]) / 100.0f;
}
float aNormal(int i, float pct) {
  return 100.0f * (pct - minimo[i]) / (maximo[i] - minimo[i]);
}

void publicarEstado(const char* texto) {
  portENTER_CRITICAL(&candado);
  strncpy(pendientes.texto, texto, sizeof(pendientes.texto) - 1);
  pendientes.texto[sizeof(pendientes.texto) - 1] = '\0';
  pendientes.estado = true;
  portEXIT_CRITICAL(&candado);
}
void publicarSliders() {
  portENTER_CRITICAL(&candado);
  for (int i = 0; i < 6; i++) pendientes.porcentajes[i] = aNormal(i, destino[i]);
  pendientes.sliders = true;
  portEXIT_CRITICAL(&candado);
}
void publicarStop() {
  portENTER_CRITICAL(&candado);
  pendientes.detenido = detenido;
  pendientes.stop = true;
  portEXIT_CRITICAL(&candado);
}
void publicarVelocidad() {
  portENTER_CRITICAL(&candado);
  pendientes.vel = velocidad;
  pendientes.velocidad = true;
  portEXIT_CRITICAL(&candado);
}
void publicarXYZ(float x, float y, float z) {
  portENTER_CRITICAL(&candado);
  pendientes.x = x; pendientes.y = y; pendientes.z = z;
  pendientes.xyz = true;
  portEXIT_CRITICAL(&candado);
}
void publicarDistancia(float d) {
  portENTER_CRITICAL(&candado);
  pendientes.dist = d;
  pendientes.distancia = true;
  portEXIT_CRITICAL(&candado);
}

void escribirServo(int i) {
  int pulso = 1000 + actual[i] * 10;
  pca.writeMicroseconds(canales[i], pulso);
}
void mover() {
  if (!iniciado || detenido || millis() - ultimoPaso < 20) return;
  ultimoPaso = millis();
  float paso = 0.1f + velocidad * 0.012f;
  for (int i = 0; i < 6; i++) {
    float diferencia = destino[i] - actual[i];
    if (fabs(diferencia) < 0.01f) continue;
    if (fabs(diferencia) <= paso) actual[i] = destino[i];
    else actual[i] += (diferencia > 0 ? paso : -paso);
    escribirServo(i);
  }
}
bool moviendo() {
  for (int i = 0; i < 6; i++)
    if (fabs(destino[i] - actual[i]) > 0.01f) return true;
  return false;
}
void detener() {
  for (int i = 0; i < 6; i++) destino[i] = actual[i];
  detenido = true;
  rutinaActiva = false;
  publicarStop();
  publicarEstado("DETENIDO");
}
void activarHome() {
  if (detenido || rutinaActiva) return;
  if (!iniciado) {
    // Primera activacion: es necesario sostener previamente el brazo.
    for (int i = 0; i < 6; i++) escribirServo(i);
    iniciado = true;
  } else {
    for (int i = 0; i < 6; i++) destino[i] = 50;
  }
  publicarSliders();
  publicarEstado("LISTO");
}
bool destinoValido(float p) { return isfinite(p) && p >= 0 && p <= 100; }

float lecturaUnica() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long t = pulseIn(ECHO, HIGH, 25000);
  if (!t) return -1;
  float cm = t * 0.0343f / 2.0f;
  return cm >= 2 && cm <= 400 ? cm : -1;
}
float distancia() {
  // Mantener la mediana de 5 lecturas que usaba la calibracion.
  float v[5];
  int n = 0;
  for (int k = 0; k < 5; k++) {
    float d = lecturaUnica();
    if (d > 0) v[n++] = d;
    delay(35);
  }
  if (!n) return -1;
  for (int i = 1; i < n; i++) {
    float x = v[i];
    int j = i - 1;
    while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
    v[j + 1] = x;
  }
  return v[n / 2];
}
void guardarPinza(float abierta, float cerrada) {
  if (fabs(pinzaAbierta - abierta) > 0.01f) memoria.putFloat("abierta", abierta);
  if (fabs(pinzaCerrada - cerrada) > 0.01f) memoria.putFloat("cerrada", cerrada);
  pinzaAbierta = abierta;
  pinzaCerrada = cerrada;
}

void comando(String s) {
  // STATE tambien cuenta como latido de Python durante una rutina.
  ultimoPC = millis();
  if (s == "PING") Serial.println("LISTO,PONG");
  else if (s == "STATE") {
    if (!iniciado) { Serial.println("STATE,OFF"); return; }
    Serial.print(moviendo() ? "STATE,MOVING" : "STATE,IDLE");
    for (int i = 0; i < 6; i++) { Serial.print(","); Serial.print(aNormal(i, actual[i]), 2); }
    Serial.println();
  }
  else if (s == "HOME") {
    if (detenido || rutinaActiva) Serial.println("ERROR,HOME");
    else { activarHome(); Serial.println("LISTO,HOME"); }
  }
  else if (s == "STOP") {
    detener();
    Serial.println("LISTO,STOP");
  }
  else if (s == "RESUME") {
    detenido = false;
    publicarStop(); publicarEstado(iniciado ? "LISTO" : "SIN ACTIVAR");
    Serial.println("LISTO,RESUME");
  }
  else if (s == "OPEN" || s == "CLOSE") {
    if (!iniciado || detenido) { Serial.println("ERROR,PINZA"); return; }
    destino[5] = s == "OPEN" ? pinzaAbierta : pinzaCerrada;
    Serial.print(s == "OPEN" ? "LISTO,OPEN," : "LISTO,CLOSE,");
    Serial.println(aNormal(5, destino[5]), 2);
    publicarSliders();
  }
  else if (s.startsWith("PINZA,")) {
    float a, c;
    char extra;
    if (sscanf(s.c_str(), "PINZA,%f,%f%c", &a, &c, &extra) != 2 ||
        !destinoValido(a) || !destinoValido(c)) { Serial.println("ERROR,PINZA"); return; }
    guardarPinza(aOriginal(5, a), aOriginal(5, c));
    Serial.println("LISTO,PINZA");
  }
  else if (s == "PINZA?") {
    Serial.print("PINZA,"); Serial.print(aNormal(5, pinzaAbierta), 2);
    Serial.print(","); Serial.println(aNormal(5, pinzaCerrada), 2);
  }
  else if (s.startsWith("SPEED,")) {
    int v; char extra;
    if (sscanf(s.c_str(), "SPEED,%d%c", &v, &extra) != 1 || v < 1 || v > 100) {
      Serial.println("ERROR,SPEED"); return;
    }
    velocidad = v; publicarVelocidad();
    Serial.println("LISTO,SPEED");
  }
  else if (s == "DIST") {
    float d = distancia();
    Serial.print("DIST,");
    if (d < 0) Serial.println("NA");
    else Serial.println(d, 2);
    publicarDistancia(d);
  }
  else if (s.startsWith("SET,")) {
    int i; float p; char extra;
    if (sscanf(s.c_str(), "SET,%d,%f%c", &i, &p, &extra) != 2 ||
        !iniciado || detenido || i < 1 || i > 6 || !destinoValido(p)) {
      Serial.println("ERROR,SET"); return;
    }
    destino[i - 1] = aOriginal(i - 1, p);
    publicarSliders(); Serial.println("LISTO,SET");
  }
  else if (s.startsWith("ALL,")) {
    float p[6]; char extra;
    if (sscanf(s.c_str(), "ALL,%f,%f,%f,%f,%f,%f%c",
        &p[0], &p[1], &p[2], &p[3], &p[4], &p[5], &extra) != 6 ||
        !iniciado || detenido) { Serial.println("ERROR,ALL"); return; }
    for (int i = 0; i < 6; i++)
      if (!destinoValido(p[i])) { Serial.println("ERROR,LIMITE"); return; }
    for (int i = 0; i < 6; i++) destino[i] = aOriginal(i, p[i]);
    publicarSliders(); Serial.println("LISTO,ALL");
  }
  else if (s.startsWith("XYZ,")) {
    float x, y, z; char extra;
    if (sscanf(s.c_str(), "XYZ,%f,%f,%f%c", &x, &y, &z, &extra) != 3 ||
        !isfinite(x) || !isfinite(y) || !isfinite(z)) {
      Serial.println("ERROR,XYZ"); return;
    }
    publicarXYZ(x, y, z); Serial.println("LISTO,XYZ");
  }
  else if (s.startsWith("REPORT,")) {
    String estado = s.substring(7);
    estado.trim();
    if (estado == "TERMINADA" || estado == "DETENIDA" || estado == "ERROR")
      rutinaActiva = false;
    else if (!detenido) rutinaActiva = true;
    publicarEstado(detenido ? "DETENIDO" : estado.c_str());
    Serial.println("LISTO,REPORT");
  }
  else Serial.println("ERROR,COMANDO");
}

void atenderBlynkPedidos() {
  Pedidos p;
  portENTER_CRITICAL(&candado);
  p = pedidos;
  pedidos.stop = pedidos.resume = pedidos.iniciar = pedidos.sync = false;
  pedidos.abrir = pedidos.cerrar = false;
  pedidos.guardar = 0;
  pedidos.cambiarVelocidad = false;
  for (int i = 0; i < 6; i++) pedidos.servo[i] = false;
  portEXIT_CRITICAL(&candado);

  if (p.stop) {
    detener();
    Serial.println("STOP_REQUEST");
  }
  if (p.resume && !p.stop) {
    detenido = false;
    publicarStop();
    publicarEstado(iniciado ? "LISTO" : "SIN ACTIVAR");
    Serial.println("RESUME_REQUEST");
  }
  if (p.sync) {
    // V12 se restaura con syncVirtual; no sobrescribirlo antes de recibirlo.
    publicarSliders(); publicarStop();
    publicarEstado(detenido ? "DETENIDO" : rutinaActiva ? "EJECUTANDO" :
                   iniciado ? "LISTO" : "SIN ACTIVAR");
  }
  if (p.cambiarVelocidad && !rutinaActiva) {
    velocidad = constrain(p.nuevaVelocidad, 1, 100);
    publicarVelocidad();
  }
  if (p.guardar && !rutinaActiva) {
    if (p.guardar == 1) guardarPinza(destino[5], pinzaCerrada);
    else guardarPinza(pinzaAbierta, destino[5]);
    publicarEstado(p.guardar == 1 ? "ABIERTA GUARDADA" : "CERRADA GUARDADA");
  }
  if (!rutinaActiva && !detenido && iniciado && !p.stop) {
    bool cambio = false;
    for (int i = 0; i < 6; i++) {
      if (p.servo[i] && destinoValido(p.pct[i])) {
        destino[i] = aOriginal(i, p.pct[i]);
        cambio = true;
      }
    }
    if (p.abrir) { destino[5] = pinzaAbierta; cambio = true; }
    if (p.cerrar) { destino[5] = pinzaCerrada; cambio = true; }
    if (cambio) publicarSliders();
  }
  if (p.iniciar) {
    if (iniciado && !detenido && !rutinaActiva && !p.stop &&
        ultimoPC && millis() - ultimoPC < 5000) {
      rutinaActiva = true;                   // Blynk deja de manejar los servos
      Serial.print("RUTINA,"); Serial.println(rutinaElegida);
      publicarEstado("ESPERANDO PYTHON");
    } else publicarEstado("SIN PYTHON O SIN ACTIVAR");
  }
  if (rutinaActiva && millis() - ultimoPC > VIGILANCIA_MS) {
    detener();
    Serial.println("SIN_PYTHON");
    publicarEstado("SIN PYTHON");
  }
}

void enviarPendientes() {
  Publicaciones p;
  portENTER_CRITICAL(&candado);
  p = pendientes;
  pendientes.estado = pendientes.xyz = pendientes.sliders = false;
  pendientes.stop = pendientes.velocidad = pendientes.distancia = false;
  portEXIT_CRITICAL(&candado);

  if (p.estado) Blynk.virtualWrite(V11, p.texto);
  if (p.xyz) {
    Blynk.virtualWrite(V13, p.x); Blynk.virtualWrite(V14, p.y);
    Blynk.virtualWrite(V15, p.z);
  }
  if (p.sliders) {
    for (int i = 0; i < 5; i++) Blynk.virtualWrite(i, p.porcentajes[i]);
    Blynk.virtualWrite(V16, p.porcentajes[5]);
  }
  if (p.stop) Blynk.virtualWrite(V10, p.detenido ? 1 : 0);
  if (p.velocidad) Blynk.virtualWrite(V12, p.vel);
  if (p.distancia) Blynk.virtualWrite(V7, p.dist);
}

void tareaBlynk(void*) {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  for (int i = 0; i < N_REDES; i++)
    if (strlen(REDES[i][0])) redes.addAP(REDES[i][0], REDES[i][1]);
  Blynk.config(BLYNK_AUTH_TOKEN);
  unsigned long ultimoIntento = 0;
  for (;;) {
    bool conectado = redes.run(5000) == WL_CONNECTED;
    if (conectado) {
      if (Blynk.connected()) { Blynk.run(); enviarPendientes(); }
      else if (millis() - ultimoIntento > 5000) {
        ultimoIntento = millis();
        Blynk.connect(2000);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

void pedirServo(int i, float pct) {
  if (!destinoValido(pct)) return;
  portENTER_CRITICAL(&candado);
  pedidos.pct[i] = pct; pedidos.servo[i] = true;
  portEXIT_CRITICAL(&candado);
}
BLYNK_WRITE(V0) { pedirServo(0, param.asFloat()); }
BLYNK_WRITE(V1) { pedirServo(1, param.asFloat()); }
BLYNK_WRITE(V2) { pedirServo(2, param.asFloat()); }
BLYNK_WRITE(V3) { pedirServo(3, param.asFloat()); }
BLYNK_WRITE(V4) { pedirServo(4, param.asFloat()); }
BLYNK_WRITE(V16) { pedirServo(5, param.asFloat()); }
BLYNK_WRITE(V5) {
  if (param.asInt() == 1) {
    portENTER_CRITICAL(&candado);
    pedidos.abrir = true;
    portEXIT_CRITICAL(&candado);
  }
}
BLYNK_WRITE(V6) {
  if (param.asInt() == 1) {
    portENTER_CRITICAL(&candado);
    pedidos.cerrar = true;
    portEXIT_CRITICAL(&candado);
  }
}
BLYNK_WRITE(V17) {
  if (param.asInt() == 1) {
    portENTER_CRITICAL(&candado);
    pedidos.guardar = 1;
    portEXIT_CRITICAL(&candado);
  }
}
BLYNK_WRITE(V18) {
  if (param.asInt() == 1) {
    portENTER_CRITICAL(&candado);
    pedidos.guardar = 2;
    portEXIT_CRITICAL(&candado);
  }
}
BLYNK_WRITE(V8) {
  portENTER_CRITICAL(&candado);
  rutinaElegida = constrain(param.asInt(), 0, 3) + 1;
  portEXIT_CRITICAL(&candado);
}
BLYNK_WRITE(V9) {
  if (param.asInt() == 1) {
    portENTER_CRITICAL(&candado);
    pedidos.numeroRutina = rutinaElegida;
    pedidos.iniciar = true;
    portEXIT_CRITICAL(&candado);
  }
}
BLYNK_WRITE(V10) {
  portENTER_CRITICAL(&candado);
  if (param.asInt() == 1) pedidos.stop = true;
  else pedidos.resume = true;
  portEXIT_CRITICAL(&candado);
}
BLYNK_WRITE(V12) {
  portENTER_CRITICAL(&candado);
  pedidos.nuevaVelocidad = param.asInt();
  pedidos.cambiarVelocidad = true;
  portEXIT_CRITICAL(&candado);
}
BLYNK_CONNECTED() {
  Blynk.syncVirtual(V8, V12);
  portENTER_CRITICAL(&candado);
  pedidos.sync = true;
  portEXIT_CRITICAL(&candado);
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(30);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  Wire.begin(26, 27);
  memoria.begin("brazo", false);
  pinzaAbierta = memoria.getFloat("abierta", pinzaAbierta);
  pinzaCerrada = memoria.getFloat("cerrada", pinzaCerrada);
  if (!pca.begin()) {
    Serial.println("ERROR,PCA");
    while (true) delay(1000);
  }
  pca.setPWMFreq(50);
  delay(10);
  for (int i = 0; i < 6; i++) pca.setPWM(canales[i], 0, 4096);
  xTaskCreatePinnedToCore(tareaBlynk, "blynk", 8192, NULL, 1, NULL, 0);
  Serial.println("READY");
}

void loop() {
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    s.trim();
    if (s.length()) comando(s);
  }
  atenderBlynkPedidos();
  mover();
  if (millis() - ultimoDist > 2000 && iniciado && !moviendo() && !rutinaActiva) {
    ultimoDist = millis();
    publicarDistancia(lecturaUnica());
  }
}
