import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from src.modelo import dh
from src.controlador.comunicacion import puertos_disponibles
from src.controlador.controlador import Controlador
from src.vista.dibujo import Escena3D


class Interfaz(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Manipulador - GUI")
        self.geometry("1340x790")
        self.minsize(1030, 660)
        self.controlador = Controlador()
        self.q = dh.porcentajes_a_angulos(dh.HOME)
        self.pct_pinza = dh.HOME[5]
        self.activado = False
        self.dibujar = True
        self._cerrando = False
        self.estado = tk.StringVar(value="Sin conectar")
        self.tcp = tk.StringVar(value="X: --    Y: --    Z: --")
        self.puerto = tk.StringVar()
        self.matriz = tk.StringVar(value="T05")
        # Valores normalizados 0-100: respetan la calibracion del firmware.
        self.servo_manual = [tk.DoubleVar(value=dh.HOME[i]) for i in range(5)]
        self.pinza_manual = tk.DoubleVar(value=dh.HOME[5])
        self.pinza_abierta = tk.StringVar(value=f"{dh.PINZA_ABIERTA:.1f}")
        self.pinza_cerrada = tk.StringVar(value=f"{dh.PINZA_CERRADA:.1f}")
        self.seccion = tk.StringVar(value="Rutinas")
        self.distancia_sensor = tk.StringVar(value="-- cm")
        self._midiendo = False
        self._crear_ventana()
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(120, self._actualizar)

    def _crear_ventana(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Lateral desplazable: todos los servos, sensor y pinza caben
        # incluso en una pantalla de 790 px de alto.
        marco_lateral = ttk.Frame(self, width=290)
        marco_lateral.grid(row=0, column=0, sticky="ns")
        marco_lateral.grid_propagate(False)
        marco_lateral.rowconfigure(0, weight=1)
        marco_lateral.columnconfigure(0, weight=1)
        self.lienzo_lateral = tk.Canvas(marco_lateral, width=275,
                                       highlightthickness=0, borderwidth=0)
        self.lienzo_lateral.grid(row=0, column=0, sticky="nsew")
        scroll_lateral = ttk.Scrollbar(marco_lateral, orient="vertical",
                                      command=self.lienzo_lateral.yview)
        scroll_lateral.grid(row=0, column=1, sticky="ns")
        self.lienzo_lateral.configure(yscrollcommand=scroll_lateral.set)
        izquierdo = ttk.Frame(self.lienzo_lateral, padding=12)
        ventana_lateral = self.lienzo_lateral.create_window(
            (0, 0), window=izquierdo, anchor="nw")
        izquierdo.bind("<Configure>", lambda e: self.lienzo_lateral.configure(
            scrollregion=self.lienzo_lateral.bbox("all")))
        self.lienzo_lateral.bind("<Configure>", lambda e: self.lienzo_lateral.itemconfigure(
            ventana_lateral, width=e.width))
        centro = ttk.Frame(self, padding=6)
        centro.grid(row=0, column=1, sticky="nsew")
        centro.rowconfigure(1, weight=1)
        centro.columnconfigure(0, weight=1)
        derecho = ttk.Frame(self, padding=10)
        derecho.grid(row=0, column=2, sticky="ns")
        derecho.configure(width=405)
        derecho.grid_propagate(False)

        ttk.Label(izquierdo, text="CONEXIÓN DEL BRAZO", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 10))
        fila = ttk.Frame(izquierdo)
        fila.pack(fill="x")
        self.combo = ttk.Combobox(fila, textvariable=self.puerto, width=18)
        self.combo.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="↻", width=3, command=self._puertos).pack(side="left", padx=(4, 0))
        self._puertos()
        self.boton_conectar = ttk.Button(izquierdo, text="Conectar USB", command=self._conectar)
        self.boton_conectar.pack(fill="x", pady=(8, 8))
        ttk.Label(izquierdo, textvariable=self.estado, wraplength=240).pack(anchor="w", pady=(0, 12))
        ttk.Button(izquierdo, text="Activar / HOME", command=lambda: self._accion(self.controlador.activar)).pack(fill="x", pady=2)
        ttk.Button(izquierdo, text="STOP", command=lambda: self._accion(self.controlador.detener)).pack(fill="x", pady=2)
        ttk.Button(izquierdo, text="Reanudar", command=lambda: self._accion(self.controlador.reanudar)).pack(fill="x", pady=2)

        ttk.Separator(izquierdo).pack(fill="x", pady=(12, 10))
        ttk.Label(izquierdo, text="CONTROL DESDE PYTHON",
                  font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.selector_seccion = ttk.Combobox(
            izquierdo, textvariable=self.seccion, state="readonly",
            values=("Rutinas", "En caso de que no queden mensajes en Blynk"))
        self.selector_seccion.pack(fill="x", pady=(0, 9))
        self.selector_seccion.bind("<<ComboboxSelected>>", self._cambiar_seccion)

        self.panel_rutinas = ttk.Frame(izquierdo)
        self.panel_rutinas.pack(fill="x")
        ttk.Label(self.panel_rutinas, text="RUTINAS",
                  font=("Arial", 10, "bold")).pack(anchor="w")
        self.rutina_seleccion = tk.StringVar(value="3 - Solo escanear")
        ttk.Combobox(self.panel_rutinas, textvariable=self.rutina_seleccion,
                     values=("1 - Apilar", "2 - Ordenar en fila",
                             "3 - Solo escanear", "4 - Apilado enseñado"),
                     state="readonly").pack(fill="x", pady=(8, 5))
        self.boton_rutina = ttk.Button(self.panel_rutinas,
                                      text="Iniciar rutina desde GUI",
                                      command=self._ejecutar_rutina)
        self.boton_rutina.pack(fill="x", pady=(0, 8))

        # Panel en caso de que BLYNK supere limite de mensajes.
        self.panel_manual = ttk.Frame(izquierdo)

        ttk.Separator(self.panel_manual).pack(fill="x", pady=(2, 5))
        ttk.Label(self.panel_manual, text="SENSOR ULTRASONICO",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 3))
        fila_sensor = ttk.Frame(self.panel_manual)
        fila_sensor.pack(fill="x", pady=(0, 4))
        self.boton_medir = ttk.Button(fila_sensor, text="Medir distancia",
                                      command=self._medir_distancia)
        self.boton_medir.pack(side="left", fill="x", expand=True)
        ttk.Label(fila_sensor, textvariable=self.distancia_sensor,
                  width=10, anchor="e").pack(side="left", padx=(6, 0))


        nombres = ("S1 · Base", "S2 · Hombro", "S3 · Codo",
                   "S4 · Giro muñeca", "S5 · Muñeca")
        self.boton_servo = []
        self.servo_texto = []
        for i, nombre in enumerate(nombres):
            fila_servo = ttk.Frame(self.panel_manual)
            fila_servo.pack(fill="x", pady=1)
            ttk.Label(fila_servo, text=nombre, width=18).pack(side="left")
            t = tk.StringVar(value=f"{self.servo_manual[i].get():.1f}%")
            self.servo_texto.append(t)
            ttk.Label(fila_servo, textvariable=t, width=7).pack(side="right")
            fila_escala = ttk.Frame(self.panel_manual)
            fila_escala.pack(fill="x", pady=(0, 3))
            ttk.Scale(fila_escala, from_=0, to=100,
                      variable=self.servo_manual[i],
                      command=lambda v, k=i: self.servo_texto[k].set(f"{float(v):.1f}%")
                      ).pack(side="left", fill="x", expand=True)
            boton = ttk.Button(fila_escala, text="Mover", width=7,
                               command=lambda k=i: self._mover_servo(k))
            boton.pack(side="left", padx=(7, 0))
            self.boton_servo.append(boton)

        fila_botones = ttk.Frame(self.panel_manual)
        fila_botones.pack(fill="x", pady=(3, 6))
        self.boton_todos = ttk.Button(fila_botones, text="Mover los 5 servos",
                                        command=self._mover_cinco)
        self.boton_todos.pack(side="left", fill="x", expand=True)
        ttk.Button(fila_botones, text="Leer estado",
                   command=self._cargar_estado).pack(side="left", padx=(5, 0))

        ttk.Separator(self.panel_manual).pack(fill="x", pady=(2, 7))
        ttk.Label(self.panel_manual, text="PINZA (SERVO 6)",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 3))
        fila_pinza = ttk.Frame(self.panel_manual)
        fila_pinza.pack(fill="x", pady=(0, 5))
        self.pinza_texto = tk.StringVar(value=f"{self.pinza_manual.get():.1f}%")
        ttk.Scale(fila_pinza, from_=0, to=100, variable=self.pinza_manual,
                  command=lambda v: self.pinza_texto.set(f"{float(v):.1f}%")
                  ).pack(side="left", fill="x", expand=True)
        ttk.Label(fila_pinza, textvariable=self.pinza_texto, width=7).pack(side="left", padx=(4, 0))
        self.boton_pinza_posicion = ttk.Button(self.panel_manual,
                                              text="Mover pinza a ese porcentaje",
                                              command=self._mover_pinza)
        self.boton_pinza_posicion.pack(fill="x", pady=(0, 5))
        fila_cal = ttk.Frame(self.panel_manual)
        fila_cal.pack(fill="x", pady=(0, 5))
        ttk.Label(fila_cal, text="Abierta %").grid(row=0, column=0, sticky="w")
        ttk.Entry(fila_cal, textvariable=self.pinza_abierta, width=7).grid(row=0, column=1, padx=(3, 10))
        ttk.Label(fila_cal, text="Cerrada %").grid(row=0, column=2, sticky="w")
        ttk.Entry(fila_cal, textvariable=self.pinza_cerrada, width=7).grid(row=0, column=3, padx=(3, 0))
        self.boton_guardar_pinza = ttk.Button(
            self.panel_manual, text="Guardar apertura / cierre",
            command=self._guardar_pinza)
        self.boton_guardar_pinza.pack(fill="x", pady=(0, 4))
        fila_abrir_cerrar = ttk.Frame(self.panel_manual)
        fila_abrir_cerrar.pack(fill="x")
        self.boton_abrir = ttk.Button(fila_abrir_cerrar, text="Abrir pinza",
                                      command=lambda: self._pinza_abrir_cerrar(True))
        self.boton_abrir.pack(side="left", fill="x", expand=True)
        self.boton_cerrar = ttk.Button(fila_abrir_cerrar, text="Cerrar pinza",
                                       command=lambda: self._pinza_abrir_cerrar(False))
        self.boton_cerrar.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.controles_manuales = self.boton_servo + [
            self.boton_todos, self.boton_pinza_posicion,
            self.boton_guardar_pinza, self.boton_abrir, self.boton_cerrar]
        # Ningun movimiento habilitado antes de conectar y activar el brazo.
        self.boton_rutina.state(["disabled"])
        self.boton_medir.state(["disabled"])
        for boton in self.controles_manuales:
            boton.state(["disabled"])

        ttk.Label(centro, text="MODELO 3D · ARTICULACIONES Y EJES D-H", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        fig = Figure(figsize=(7, 6), dpi=95)
        self.ax = fig.add_subplot(111, projection="3d")
        self.escena = Escena3D(self.ax)
        self.lienzo = FigureCanvasTkAgg(fig, master=centro)
        self.lienzo.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        ttk.Label(centro, textvariable=self.tcp, font=("Consolas", 12, "bold")).grid(row=2, column=0, sticky="w", pady=8)
        ttk.Label(centro, text="La posición mostrada se calcula desde STATE; los servos no tienen encoder.").grid(row=3, column=0, sticky="w")

        ttk.Label(derecho, text="PARÁMETROS D-H", font=("Arial", 12, "bold")).pack(anchor="w", pady=(0, 8))
        columnas = ("eje", "theta", "d", "a", "alpha")
        self.tabla = ttk.Treeview(derecho, columns=columnas, show="headings", height=5)
        for c, ancho in zip(columnas, (38, 84, 65, 65, 76)):
            self.tabla.heading(c, text=c)
            self.tabla.column(c, width=ancho, anchor="center")
        self.tabla.pack(fill="x")
        for i in range(1, 6):
            self.tabla.insert("", "end", iid=str(i), values=(i, "", "", "", ""))

        ttk.Label(derecho, text="TRANSFORMACIONES", font=("Arial", 12, "bold")).pack(anchor="w", pady=(20, 7))
        opciones = [f"A{i}" for i in range(1, 6)] + [f"T0{i}" for i in range(1, 6)]
        selector = ttk.Combobox(derecho, values=opciones, state="readonly", textvariable=self.matriz)
        selector.pack(fill="x")
        selector.bind("<<ComboboxSelected>>", lambda _: self._redibujar())
        self.caja_matriz = tk.Text(derecho, height=8, width=38, font=("Courier New", 11), state="disabled")
        self.caja_matriz.pack(fill="x", pady=9)
        ttk.Label(derecho, text="T05: transformación de la base a la pinza").pack(anchor="w")
        self.caja_total = tk.Text(derecho, height=6, width=38, font=("Courier New", 10), state="disabled")
        self.caja_total.pack(fill="x", pady=7)

        ttk.Label(derecho, text="REGISTRO", font=("Arial", 11, "bold")).pack(anchor="w", pady=(13, 4))
        self.log = tk.Listbox(derecho, height=9, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self._redibujar()

    def _puertos(self):
        puertos = puertos_disponibles()
        self.combo["values"] = puertos
        if puertos and self.puerto.get() not in puertos:
            self.puerto.set(puertos[0])

    def _conectar(self):
        puerto = self.puerto.get().strip()
        if not puerto:
            messagebox.showerror("Puerto", "Selecciona el puerto del ESP32")
            return
        self.boton_conectar.state(["disabled"])
        self.estado.set("Conectando por USB...")
        self._accion(self.controlador.conectar, puerto, boton=self.boton_conectar)

    def _accion(self, funcion, *args, boton=None):
        def trabajo():
            try:
                funcion(*args)
            except Exception as e:
                self.controlador.avisar("error", str(e))
            finally:
                if boton is not None:
                    self.controlador.avisar("boton", boton)
        threading.Thread(target=trabajo, daemon=True).start()

    def _cambiar_seccion(self, _evento=None):
        self.lienzo_lateral.yview_moveto(0)
        self.panel_rutinas.pack_forget()
        self.panel_manual.pack_forget()
        if self.seccion.get() == "En caso de que no queden mensajes en Blynk":
            self.panel_manual.pack(fill="x")
            if self.controlador.robot is not None:
                # Lee la calibracion guardada en el ESP32 sin cambiarla.
                self._accion(self.controlador.leer_calibracion_pinza)
        else:
            self.panel_rutinas.pack(fill="x")

    def _cargar_estado(self):
        if self.controlador.robot is None:
            messagebox.showerror("Sin conexion", "Conecta primero el ESP32 por USB")
            return
        valores = list(self.controlador.porcentajes)
        for i in range(5):
            self.servo_manual[i].set(valores[i])
            self.servo_texto[i].set(f"{valores[i]:.1f}%")
        self.pinza_manual.set(valores[5])
        self.pinza_texto.set(f"{valores[5]:.1f}%")

    def _medir_distancia(self):
        if self.controlador.robot is None:
            messagebox.showerror("Sin conexion", "Conecta primero el ESP32 por USB")
            return
        if self.controlador.rutina_activa():
            messagebox.showinfo("Rutina en curso", "Espera a que termine para medir")
            return
        if self._midiendo:
            return
        self.distancia_sensor.set("Midiendo...")
        self._midiendo = True
        self.boton_medir.state(["disabled"])
        self._accion(self.controlador.leer_distancia_sensor, boton=self.boton_medir)

    def _mover_servo(self, i):
        if not self._permite_manual():
            return
        p = round(self.servo_manual[i].get(), 1)
        self._accion(self.controlador.mover_servo_manual, i + 1, p)

    def _mover_cinco(self):
        if not self._permite_manual():
            return
        valores = [round(p.get(), 1) for p in self.servo_manual]
        self._accion(self.controlador.mover_cinco_manual, valores)

    def _mover_pinza(self):
        if self._permite_manual():
            self._accion(self.controlador.mover_pinza_manual,
                         round(self.pinza_manual.get(), 1))

    def _guardar_pinza(self):
        if not self._permite_manual():
            return
        try:
            abierta = float(self.pinza_abierta.get().replace(",", "."))
            cerrada = float(self.pinza_cerrada.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Pinza", "Ingresa porcentajes numericos")
            return
        if not (0 <= abierta <= 100 and 0 <= cerrada <= 100):
            messagebox.showerror("Pinza", "Los porcentajes deben estar entre 0 y 100")
            return
        self._accion(self.controlador.configurar_pinza_manual, abierta, cerrada)

    def _pinza_abrir_cerrar(self, abrir):
        if self._permite_manual():
            self._accion(self.controlador.pinza_manual, abrir)

    def _permite_manual(self):
        if self.controlador.robot is None:
            messagebox.showerror("Sin conexion", "Conecta primero el ESP32 por USB")
            return False
        if self.controlador.rutina_activa():
            messagebox.showinfo("Rutina en curso", "No controles los servos mientras se ejecuta una rutina")
            return False
        if self.controlador._detenido or not self.activado:
            messagebox.showerror("Brazo no disponible", "Activa HOME o utiliza Reanudar antes de mover")
            return False
        return True

    def _ejecutar_rutina(self):
        if self.controlador.robot is None:
            messagebox.showerror("Sin conexión", "Conecta primero el ESP32 por USB.")
            return
        if self.controlador.rutina_activa():
            messagebox.showinfo("Rutina en curso", "Espera a que termine la rutina actual.")
            return
        if self.controlador._detenido:
            messagebox.showerror("Brazo detenido", "Utiliza Reanudar antes de ejecutar.")
            return
        numero = int(self.rutina_seleccion.get().split(" ", 1)[0])
        self._accion(self.controlador.iniciar_rutina, numero)

    def _poner_texto(self, widget, texto):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", texto)
        widget.configure(state="disabled")

    def _redibujar(self):
        A, T = dh.matrices(self.q)
        for i, (theta, d, a, alfa) in enumerate(dh.parametros_dh(self.q), 1):
            self.tabla.item(str(i), values=(i, f"{theta:.1f}°", f"{d:.2f}", f"{a:.2f}", f"{alfa:.0f}°"))
        sel = self.matriz.get()
        indice = int(sel[-1])
        M = A[indice - 1] if sel.startswith("A") else T[indice]
        formatear = lambda mat: "\n".join("[ " + " ".join(f"{v:7.3f}" for v in fila) + " ]" for fila in mat)
        self._poner_texto(self.caja_matriz, f"{sel}\n\n" + formatear(M))
        self._poner_texto(self.caja_total, formatear(T[5]))
        x, y, z = dh.cinematica_directa(self.q)
        self.tcp.set(f"TCP: X={x:.2f}   Y={y:.2f}   Z={z:.2f} cm")
        self.escena.actualizar(T, pinza_pct=self.pct_pinza, resaltados=(indice,),
                             ver_ejes=True, ver_etiq=True, esc=3.0)
        self.lienzo.draw_idle()
        self.dibujar = False

    def _actualizar(self):
        try:
            ultima_pose = None
            while True:
                tipo, *datos = self.controlador.avisos.get_nowait()
                if tipo == "cerrar":
                    self.destroy()
                    return
                if tipo == "pose":
                    ultima_pose = datos
                elif tipo == "conexion":
                    self.estado.set("ESP32 conectado. Pulsa Activar / HOME.")
                elif tipo == "boton":
                    if datos[0] is self.boton_medir:
                        self._midiendo = False
                    datos[0].state(["!disabled"])
                elif tipo == "distancia_sensor":
                    distancia = datos[0]
                    self.distancia_sensor.set(
                        "Sin eco" if distancia is None else f"{distancia:.2f} cm")
                elif tipo == "calibracion_pinza":
                    abierta, cerrada = datos
                    self.pinza_abierta.set(f"{abierta:.1f}")
                    self.pinza_cerrada.set(f"{cerrada:.1f}")
                elif tipo == "error":
                    if self._midiendo:
                        self.distancia_sensor.set("Error")
                    self.estado.set("ERROR: " + datos[0])
                    self._log(datos[0])
                elif tipo == "log":
                    self._log(datos[0])
                elif tipo == "fin":
                    self._log("Rutina finalizada: " + datos[0])
                elif tipo == "progreso":
                    pass
                elif tipo == "deteccion":
                    self._log("Detección en " + datos[0]["nombre"])
        except queue.Empty:
            pass
        if ultima_pose:
            q, pcts, activado, moviendo = ultima_pose
            if (max(abs(a - b) for a, b in zip(q, self.q)) > 0.03 or
                abs(pcts[5] - self.pct_pinza) > 0.15 or self.dibujar):
                self.q = q
                self.pct_pinza = pcts[5]
                self._redibujar()
            self.activado = activado
            if self.controlador._detenido:
                self.estado.set("DETENIDO")
            elif self.controlador.rutina_activa():
                self.estado.set("RUTINA EN CURSO" if activado else "SIN ACTIVAR")
            else:
                self.estado.set("MOVIENDO" if moviendo else "LISTO" if activado else "SIN ACTIVAR")
        if (self.controlador.robot is None or
                self.controlador.rutina_activa() or
                self.controlador._detenido or not self.activado):
            self.boton_rutina.state(["disabled"])
        else:
            self.boton_rutina.state(["!disabled"])
        # No permitir movimientos manuales durante rutinas ni con STOP activo.
        manual_habilitado = (self.controlador.robot is not None and
                             not self.controlador.rutina_activa() and
                             not self.controlador._detenido and self.activado)
        for boton in self.controles_manuales:
            boton.state(["!disabled"] if manual_habilitado else ["disabled"])
        # Se puede medir sin HOME, incluso despues de STOP; no durante una rutina.
        medir_habilitado = (self.controlador.robot is not None and
                            not self.controlador.rutina_activa() and
                            not self._midiendo)
        self.boton_medir.state(["!disabled"] if medir_habilitado else ["disabled"])
        if not self._cerrando:
            self.after(120, self._actualizar)

    def _log(self, texto):
        import time
        self.log.insert("end", time.strftime("%H:%M:%S ") + str(texto))
        if self.log.size() > 150:
            self.log.delete(0, 35)
        self.log.see("end")

    def _cerrar(self):
        if self._cerrando:
            return
        # Al cerrar se solicita la detencion y desconexion mediante el controlador.
        self._cerrando = True
        self.estado.set("Deteniendo y cerrando puerto...")
        def trabajo():
            self.controlador.cerrar()
            self.controlador.avisar("cerrar")
        threading.Thread(target=trabajo, daemon=True).start()
