# Manipulador Robótico — Fundamentos de Robótica

Proyecto de un brazo robótico de 6 servomotores controlado con un ESP32. Utiliza Python para ejecutar rutinas, calcular la cinemática y mostrar el brazo en 3D. Desde Blynk podemos mover los servos y solicitar una rutina.

## Componentes

- ESP32 y módulo PCA9685.
- 6 servomotores (MG995, MG90S y SG90).
- Sensor ultrasónico HC-SR04.
- Fuente externa de 5 V para los servos.

## Organización

```text
main.py                  # Inicia el programa
firmware/                # Código del ESP32
src/modelo/              # D-H, cinemática inversa y calibraciones
src/controlador/         # Comunicación USB y rutinas
src/vista/               # Interfaz, matrices y modelo 3D
tests/                   # Pruebas del programa
```

**Python debe permanecer abierto y el ESP32 conectado por USB para ejecutar las rutinas.**

## Rutinas

1. **Apilar:** busca cajas en A y B y calcula los movimientos para apilarlas.
2. **Ordenar:** intenta colocar las cajas en fila.
3. **Escanear:** comprueba la presencia de objetos sin recogerlos.
4. **Apilado enseñado:** recoge y apila dos cajas usando posiciones calibradas.

Las rutinas se ejecutan en **Python**; el ESP32 recibe las posiciones y controla los servos. La interfaz muestra las matrices D-H, las coordenadas calculadas y una representación 3D del brazo.
