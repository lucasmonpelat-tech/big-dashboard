"""
setup_credentials_gui.py
=========================
Formulario visual para guardar credenciales de NetX360+ y Gmail en Windows
Credential Manager (encriptado).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import keyring


def save_all():
    user = e_user.get().strip()
    pw = e_pw.get().strip()
    email = e_email.get().strip()
    apppass = e_apppass.get().strip().replace(" ", "")  # quitar espacios del App Password

    missing = []
    if not user: missing.append("Usuario NetX360+")
    if not pw: missing.append("Password NetX360+")
    if not email: missing.append("Gmail email")
    if not apppass: missing.append("Gmail App Password")

    if missing:
        messagebox.showwarning("Faltan datos", "Completar:\n\n- " + "\n- ".join(missing))
        return

    try:
        keyring.set_password("big-netx360", "user", user)
        keyring.set_password("big-netx360", "pass", pw)
        keyring.set_password("big-gmail-otp", "email", email)
        keyring.set_password("big-gmail-otp", "apppass", apppass)
        messagebox.showinfo("OK", "Credenciales guardadas en Windows Credential Manager.\n\nEncriptadas y solo tu usuario puede leerlas.")
        root.destroy()
    except Exception as ex:
        messagebox.showerror("Error", f"No se pudo guardar:\n{ex}")


root = tk.Tk()
root.title("Setup Credenciales - Big Dashboard")
root.geometry("520x400")
root.resizable(False, False)

# Frame principal con padding
main = ttk.Frame(root, padding=20)
main.pack(fill="both", expand=True)

# Titulo
title = ttk.Label(main, text="Credenciales Big Dashboard", font=("Segoe UI", 14, "bold"))
title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))

subtitle = ttk.Label(main, text="Se guardan encriptadas en Windows Credential Manager.\nSolo tu usuario puede leerlas.",
                     foreground="#666", font=("Segoe UI", 9))
subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15))

# Separador
ttk.Separator(main, orient="horizontal").grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)

# Seccion NetX360
lbl_netx = ttk.Label(main, text="NetX360+", font=("Segoe UI", 10, "bold"))
lbl_netx.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 5))

ttk.Label(main, text="Usuario:").grid(row=4, column=0, sticky="w", pady=3)
e_user = ttk.Entry(main, width=40)
e_user.grid(row=4, column=1, sticky="ew", pady=3)

ttk.Label(main, text="Password:").grid(row=5, column=0, sticky="w", pady=3)
e_pw = ttk.Entry(main, width=40, show="•")
e_pw.grid(row=5, column=1, sticky="ew", pady=3)

# Seccion Gmail
lbl_gmail = ttk.Label(main, text="Gmail (para leer OTPs)", font=("Segoe UI", 10, "bold"))
lbl_gmail.grid(row=6, column=0, columnspan=2, sticky="w", pady=(15, 5))

ttk.Label(main, text="Email:").grid(row=7, column=0, sticky="w", pady=3)
e_email = ttk.Entry(main, width=40)
e_email.insert(0, "monpelatlucas@gmail.com")  # pre-cargado
e_email.grid(row=7, column=1, sticky="ew", pady=3)

ttk.Label(main, text="App Password:").grid(row=8, column=0, sticky="w", pady=3)
e_apppass = ttk.Entry(main, width=40, show="•")
e_apppass.grid(row=8, column=1, sticky="ew", pady=3)

# Nota App Password
note = ttk.Label(main,
                 text="(16 chars de https://myaccount.google.com/apppasswords)",
                 foreground="#888", font=("Segoe UI", 8))
note.grid(row=9, column=1, sticky="w", pady=(0, 10))

# Boton guardar
btn = ttk.Button(main, text="Guardar credenciales", command=save_all)
btn.grid(row=10, column=0, columnspan=2, pady=(15, 0), ipadx=20, ipady=5)

main.columnconfigure(1, weight=1)

# Focus al primer campo
e_user.focus()

root.mainloop()
