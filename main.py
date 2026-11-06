from src.vista.gui import Interfaz

def iniciar():
    # Al crear la vista se crea tambien el controlador y su hilo de lectura.
    ventana = Interfaz()
    ventana.mainloop()


if __name__ == "__main__":
    iniciar()
