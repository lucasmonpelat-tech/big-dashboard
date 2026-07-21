"""Solo actualiza el Gmail App Password."""
import tkinter as tk
from tkinter import ttk, messagebox
import keyring


def save():
    v = e.get().strip().replace(" ", "")
    if not v:
        messagebox.showwarning("Falta", "Pega el App Password de 16 chars")
        return
    if len(v) != 16:
        r = messagebox.askyesno(
            "Longitud inesperada",
            f"El password tiene {len(v)} chars.\nLos App Passwords de Gmail son de 16 chars.\n\nGuardar igual?"
        )
        if not r:
            return
    keyring.set_password("big-gmail-otp", "apppass", v)
    messagebox.showinfo("OK", f"App Password guardado ({len(v)} chars).")
    root.destroy()


root = tk.Tk()
root.title("Actualizar Gmail App Password")
root.geometry("450x180")

m = ttk.Frame(root, padding=20)
m.pack(fill="both", expand=True)

ttk.Label(m, text="Gmail App Password (16 chars)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
ttk.Label(m, text="Generalo en https://myaccount.google.com/apppasswords\nSe puede pegar con Ctrl+V. Espacios se quitan solos.",
          foreground="#666", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

e = ttk.Entry(m, width=40, show="•")
e.pack(fill="x", pady=5)
e.focus()

ttk.Button(m, text="Guardar", command=save).pack(pady=10, ipadx=20)

root.mainloop()
