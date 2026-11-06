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
        self.title("Manipulador | D-H en vivo")
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
        self.xyz = [tk.StringVar(value=v) for v in ("20", "0", "5", "-25")]
        self._crear_ventana()
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(120, self._actualizar)

    def _crear_ventana(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        izquierdo = ttk.Frame(self, padding=12)
        izquierdo.grid(row=0, column=0, sticky="ns")
        izquierdo.configure(width=265)
        izquierdo.grid_propagate(False)
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

        ttk.Separator(izquierdo).pack(fill="x", pady=16)
        ttk.Label(izquierdo, text="RUTINAS DESDE BLYNK", font=("Arial", 11, "bold")).pack(anchor="w")
        ttk.Label(izquierdo, text=(
            "1. Selecciona la rutina en Blynk (V8).\n"
            "2. Pulsa EJECUTAR (V9).\n"
            "3. Python recibe RUTINA,n y mueve el brazo.\n\n"
            "Deja este programa abierto y conectado."
        ), wraplength=238, justify="left").pack(anchor="w", pady=(8, 12))

        ttk.Separator(izquierdo).pack(fill="x", pady=12)
        ttk.Label(izquierdo, text="PRUEBA DE CINEMÁTICA INVERSA", font=("Arial", 10, "bold")).pack(anchor="w")
        campos = ttk.Frame(izquierdo)
        campos.pack(fill="x", pady=6)
        for i, nombre in enumerate(("X [cm]", "Y [cm]", "Z [cm]", "φ [°]")):
            ttk.Label(campos, text=nombre).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(campos, textvariable=self.xyz[i], width=11).grid(row=i, column=1, sticky="e", pady=3)
        ttk.Button(izquierdo, text="Resolver y mover", command=self._mover_xyz).pack(fill="x", pady=5)
        ttk.Label(izquierdo, text="Usar solo con recorrido físico despejado.", wraplength=230).pack(anchor="w")

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

    def _mover_xyz(self):
        try:
            x, y, z, phi = [float(var.get().replace(",", ".")) for var in self.xyz]
        except ValueError:
            messagebox.showerror("Coordenadas", "Ingresa números válidos")
            return
        if not messagebox.askyesno("Mover el brazo", "¿Está despejada toda la trayectoria física?"):
            return
        self._accion(self.controlador.resolver_y_mover, x, y, z, phi)

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
                    datos[0].state(["!disabled"])
                elif tipo == "error":
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
        if self.controlador.rutina_activa():
            if not messagebox.askyesno("Cerrar", "Hay una rutina en curso. ¿Detenerla y cerrar?"):
                return
        self._cerrando = True
        self.estado.set("Deteniendo y cerrando puerto...")
        def trabajo():
            self.controlador.cerrar()
            self.controlador.avisar("cerrar")
        threading.Thread(target=trabajo, daemon=True).start()
