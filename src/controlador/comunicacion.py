import queue
import threading
import time

from src.modelo import dh

EVENTOS = ("RUTINA,", "STOP_REQUEST", "RESUME_REQUEST", "SIN_PYTHON", "READY", "ERROR,PCA", "INFO,")


class ErrorRobot(Exception):
    pass


def puertos_disponibles():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


# ======================================================================
# ESP32 real
# ======================================================================
class ESP32:
    simulado = False

    def __init__(self, puerto, baudios=115200):
        try:
            import serial
        except ImportError as e:
            raise ErrorRobot("Falta pyserial:  pip install pyserial") from e
        self.ser = serial.Serial(puerto, baudios, timeout=0.05)
        self.respuestas = queue.Queue()
        self.eventos = queue.Queue()
        self._lock = threading.Lock()
        self._vivo = True
        self.pinza_objetivo = dh.HOME[5]
        self.activado = False
        threading.Thread(target=self._leer, daemon=True).start()

        # Abrir el puerto reinicia el ESP32: esperamos READY o respondemos a PING
        limite = time.time() + 6
        while time.time() < limite:
            try:
                self.comando("PING", ("LISTO,PONG",), timeout=0.8)
                return
            except ErrorRobot:
                pass
        self.cerrar()
        raise ErrorRobot(f"El ESP32 no responde en {puerto}")

    def _leer(self):
        buf = b""
        while self._vivo:
            try:
                buf += self.ser.read(256)
            except Exception:          # puerto desconectado
                self.eventos.put("DESCONECTADO")
                return
            while b"\n" in buf:
                linea, buf = buf.split(b"\n", 1)
                txt = linea.decode("utf-8", "ignore").strip()
                if not txt:
                    continue
                if txt.startswith(EVENTOS):
                    self.eventos.put(txt)
                else:
                    self.respuestas.put(txt)

    def comando(self, texto, esperado, timeout=3.0):
        with self._lock:
            while not self.respuestas.empty():          # restos de un timeout anterior
                self.respuestas.get_nowait()
            try:
                self.ser.write((texto + "\n").encode())
            except Exception as e:
                raise ErrorRobot("Puerto USB desconectado") from e
            fin = time.time() + timeout
            while True:
                resto = fin - time.time()
                if resto <= 0:
                    raise ErrorRobot(f"Sin respuesta a {texto.split(',')[0]}")
                try:
                    r = self.respuestas.get(timeout=resto)
                except queue.Empty:
                    continue
                if r.startswith(esperado):
                    return r
                if r.startswith("ERROR"):
                    raise ErrorRobot(r)

    # ---- comandos -------------------------------------------------------
    def estado(self):
        partes = self.comando("STATE", ("STATE,",)).split(",")
        self.activado = partes[1] != "OFF"
        if not self.activado:
            return False, list(dh.HOME)
        if len(partes) != 8:
            raise ErrorRobot("Respuesta STATE incompleta")
        porcentajes = [float(v) for v in partes[2:8]]
        self.pinza_objetivo = porcentajes[5]   # Puede cambiar desde el slider V16
        return partes[1] == "MOVING", porcentajes

    def mover_todos(self, pcts6):
        self.comando("ALL," + ",".join(f"{p:.2f}" for p in pcts6), ("LISTO,ALL",))
        self.pinza_objetivo = pcts6[5]

    def pinza(self, abrir):
        r = self.comando("OPEN" if abrir else "CLOSE", ("LISTO,OPEN", "LISTO,CLOSE")).split(",")
        # El ESP32 responde con el % donde quedo la pinza (se ajusta desde la app, V16-V18)
        if len(r) > 2:
            self.pinza_objetivo = float(r[2])
        else:
            self.pinza_objetivo = dh.PINZA_ABIERTA if abrir else dh.PINZA_CERRADA

    def configurar_pinza(self, abierta, cerrada):
        self.comando(f"PINZA,{abierta:.2f},{cerrada:.2f}", ("LISTO,PINZA",))

    def distancia(self):
        r = self.comando("DIST", ("DIST,",), timeout=4.0).split(",")[1]
        return None if r == "NA" else float(r)

    def velocidad(self, v):
        self.comando(f"SPEED,{int(v)}", ("LISTO,SPEED",))

    def home(self):
        self.comando("HOME", ("LISTO,HOME",))
        self.activado = True

    def stop(self):
        self.comando("STOP", ("LISTO,STOP",))

    def resume(self):
        self.comando("RESUME", ("LISTO,RESUME",))

    def publicar_xyz(self, x, y, z):
        self.comando(f"XYZ,{x:.2f},{y:.2f},{z:.2f}", ("LISTO,XYZ",))

    def reportar(self, texto):
        self.comando("REPORT," + texto.replace(",", " ")[:30], ("LISTO,REPORT",))

    def cerrar(self):
        self._vivo = False
        try:
            self.ser.close()
        except Exception:
            pass


