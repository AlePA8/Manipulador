import queue
import threading
import time

from src.modelo import dh
from src.controlador.comunicacion import ESP32, ErrorRobot
from src.modelo.inversa import cinematica_inversa
from src.controlador.rutinas import NOMBRES_RUTINA, Rutina


class Controlador:
    def __init__(self):
        self.robot = None
        self.rutina = None
        self.hilo_rutina = None
        self.avisos = queue.Queue()
        self.q = dh.porcentajes_a_angulos(dh.HOME)
        self.porcentajes = list(dh.HOME)
        self._detenido = False
        self._vivo = True
        self._lock = threading.Lock()
        self._ultimo_xyz = 0
        self._hilo = threading.Thread(target=self._atender, daemon=True)
        self._hilo.start()

    def avisar(self, tipo, *datos):
        self.avisos.put((tipo, *datos))

    def conectar(self, puerto):
        if self.robot is not None:
            raise ErrorRobot("Ya hay un brazo conectado")
        robot = ESP32(puerto)
        with self._lock:
            self.robot = robot
        self.avisar("log", f"Conectado: {puerto}. Activa el brazo antes de moverlo.")
        self.avisar("conexion", True)

    def _exigir_robot(self):
        if self.robot is None:
            raise ErrorRobot("Primero conecta el ESP32")
        return self.robot

    def _exigir_libre(self):
        robot = self._exigir_robot()
        if self.rutina_activa():
            raise ErrorRobot("Hay una rutina en curso")
        if self._detenido:
            raise ErrorRobot("El brazo esta detenido; usa Reanudar")
        return robot

    def rutina_activa(self):
        return self.hilo_rutina is not None and self.hilo_rutina.is_alive()

    def activar(self):
        robot = self._exigir_libre()
        robot.home()
        self.avisar("log", "Servos activados / orden HOME enviada")

    def reanudar(self):
        robot = self._exigir_robot()
        robot.resume()
        self._detenido = False
        self.avisar("log", "Brazo desbloqueado (la rutina cancelada no se reinicia)")

    def detener(self):
        if self.rutina is not None:
            self.rutina.parar.set()
        self._detenido = True
        robot = self._exigir_robot()
        robot.stop()
        self.avisar("log", "STOP enviado al brazo")

    # Control manual por USB cuando Blynk no este disponible.
    # Los porcentajes son normalizados 0-100, dentro de limites calibrados.
    def _manual_disponible(self):
        robot = self._exigir_libre()
        if not robot.activado:
            raise ErrorRobot("Activa HOME antes de mover los servos")
        return robot

    def mover_servo_manual(self, numero, porcentaje):
        robot = self._manual_disponible()
        if numero not in range(1, 6) or not 0 <= porcentaje <= 100:
            raise ErrorRobot("Servo o porcentaje fuera de rango")
        robot.comando(f"SET,{numero},{porcentaje:.2f}", ("LISTO,SET",))
        self.avisar("log", f"Manual: servo {numero} a {porcentaje:.1f}%")

    def mover_cinco_manual(self, valores):
        robot = self._manual_disponible()
        if len(valores) != 5 or any(not 0 <= v <= 100 for v in valores):
            raise ErrorRobot("Porcentajes fuera de rango")
        robot.mover_todos(list(valores) + [robot.pinza_objetivo])
        self.avisar("log", "Manual: movimiento conjunto de 5 servos enviado")

    def mover_pinza_manual(self, porcentaje):
        robot = self._manual_disponible()
        if not 0 <= porcentaje <= 100:
            raise ErrorRobot("Porcentaje de pinza fuera de rango")
        robot.comando(f"SET,6,{porcentaje:.2f}", ("LISTO,SET",))
        robot.pinza_objetivo = porcentaje
        self.avisar("log", f"Manual: pinza a {porcentaje:.1f}%")

    def configurar_pinza_manual(self, abierta, cerrada):
        robot = self._manual_disponible()
        if not 0 <= abierta <= 100 or not 0 <= cerrada <= 100:
            raise ErrorRobot("Calibracion de pinza fuera de rango")
        robot.configurar_pinza(abierta, cerrada)
        self.avisar("log", f"Pinza calibrada: abierta {abierta:.1f}%, cerrada {cerrada:.1f}%")

    def pinza_manual(self, abrir):
        robot = self._manual_disponible()
        robot.pinza(abrir)
        self.avisar("log", "Manual: pinza abierta" if abrir else "Manual: pinza cerrada")

    def leer_calibracion_pinza(self):
        robot = self._exigir_robot()
        resp = robot.comando("PINZA?", ("PINZA,",)).split(",")
        if len(resp) != 3:
            raise ErrorRobot("No se pudo leer la calibracion de pinza")
        self.avisar("calibracion_pinza", float(resp[1]), float(resp[2]))

    def leer_distancia_sensor(self):
        # El ultrasónico se consulta sin mover ningún servo.
        robot = self._exigir_robot()
        if self.rutina_activa():
            raise ErrorRobot("No medir manualmente durante una rutina")
        distancia = robot.distancia()
        self.avisar("distancia_sensor", distancia)
        if distancia is None:
            self.avisar("log", "Ultrasonico: sin eco")
        else:
            self.avisar("log", f"Ultrasonico: {distancia:.2f} cm")

    def resolver_y_mover(self, x, y, z, phi):
        robot = self._exigir_libre()
        if not robot.activado:
            raise ErrorRobot("Activa los servos primero con HOME")
        # La cinemática inversa calcula el destino; D-H lo comprueba.
        q = cinematica_inversa(x, y, z, phi, self.q)
        if q is None:
            raise ErrorRobot("La coordenada no es alcanzable con estos limites")
        p = dh.angulos_a_porcentajes(q)
        if p is None:
            raise ErrorRobot("Porcentaje fuera de los limites")
        robot.mover_todos(p + [robot.pinza_objetivo])
        self.avisar("log", f"Inversa: X={x:.1f}, Y={y:.1f}, Z={z:.1f} cm")

    def iniciar_rutina(self, numero):
        if numero not in NOMBRES_RUTINA:
            self.avisar("log", f"Rutina {numero} desconocida")
            return
        try:
            robot = self._exigir_libre()
            if not robot.activado:
                raise ErrorRobot("Activa HOME antes de ejecutar la rutina")
        except ErrorRobot as e:
            self.avisar("log", str(e))
            if self.robot is not None:
                try:
                    self.robot.reportar("ERROR")
                except ErrorRobot:
                    pass
            return
        self.rutina = Rutina(robot, self.avisar)
        self.hilo_rutina = threading.Thread(
            target=self.rutina.ejecutar, args=(numero,), daemon=True)
        self.hilo_rutina.start()
        self.avisar("log", f"Python ejecuta rutina {numero}: {NOMBRES_RUTINA[numero]}")

    def _atender(self):
        while self._vivo:
            robot = self.robot
            if robot is None:
                time.sleep(0.1)
                continue
            # Eventos del ESP32: V9 solo solicita; Python hace el trabajo.
            try:
                while True:
                    ev = robot.eventos.get_nowait()
                    if ev.startswith("RUTINA,"):
                        try:
                            numero = int(ev.split(",", 1)[1])
                        except ValueError:
                            self.avisar("log", f"Evento incorrecto: {ev}")
                        else:
                            self.iniciar_rutina(numero)
                    elif ev == "STOP_REQUEST" or ev == "SIN_PYTHON":
                        self._detenido = True
                        if self.rutina is not None:
                            self.rutina.parar.set()
                        self.avisar("log", "Detenido desde Blynk / por desconexion")
                    elif ev == "RESUME_REQUEST":
                        self._detenido = False
                        self.avisar("log", "Reanudado desde Blynk")
                    elif ev == "DESCONECTADO":
                        self._detenido = True
                        if self.rutina is not None:
                            self.rutina.parar.set()
                        self.avisar("log", "Conexion USB perdida")
                    elif ev.startswith(("ERROR,", "INFO,")):
                        self.avisar("log", ev)
            except queue.Empty:
                pass

            try:
                en_movimiento, pcts = robot.estado()
                self.porcentajes = pcts
                self.q = dh.porcentajes_a_angulos(pcts)
                self.avisar("pose", list(self.q), list(pcts), robot.activado, en_movimiento)
                if robot.activado and time.monotonic() - self._ultimo_xyz > 0.7:
                    self._ultimo_xyz = time.monotonic()
                    robot.publicar_xyz(*dh.cinematica_directa(self.q))
            except Exception as e:
                if self._vivo:
                    self.avisar("log", f"Lectura: {e}")
            time.sleep(0.25)

    def cerrar(self):
        self._vivo = False
        if self.robot is not None:
            if self.rutina is not None:
                self.rutina.parar.set()
            # Cerrar mientras se mueve no debe dejar una orden en curso.
            try:
                self.robot.stop()
            except Exception:
                pass
            self.robot.cerrar()
            self.robot = None
