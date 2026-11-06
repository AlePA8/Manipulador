#pragma once
#define BLYNK_AUTH_TOKEN "TOKEN_DE_BLYNK"

// El ESP32 intentara conectarse a cualquiera de estas redes de la lista.
// Solo admite WiFi de 2.4 GHz.
const char* REDES[][2] = {
  {"NOMBRE_WIFI", "CLAVE_WIFI"},
  {"OTRA_WIFI",   "OTRA_CLAVE"},
};

const int N_REDES = sizeof(REDES) / sizeof(REDES[0]);
