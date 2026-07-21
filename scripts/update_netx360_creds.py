"""Solo actualiza el user + password de NetX360+."""
import tkinter as tk
from tkinter import ttk, messagebox
import keyring


def save():
    user = e_user.get().strip()
    pw = e_pw.get().strip()

    if not user or not pw:
        messagebox.showwarning("Falta", "Completá usuario y password")
        return

    keyring.set_password("big-netx360", "user", user)
    keyring.set_password("big-netx360", "pass", pw)
    messagebox.showinfo("OK", f"Credenciales NetX360+ actualizadas:\n\nUsuario: {user}\nPassword: {len(pw)} chars")
    root.destroy()


root = tk.Tk()
root.title("Actualizar NetX360+ (user + pass)")
root.geometry("470x230")

m = ttk.Frame(root, padding=20)
m.pack(fill="both", expand=True)

ttk.Label(m, text="NetX360+ Credentials", font=("Segoe UI", 11, "bold")).pack(anchor="w")
ttk.Label(m, text="Actualizá usuario y password.\nSe puede pegar con Ctrl+V.",
          foreground="#666", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

ttk.Label(m, text="Usuario:").pack(anchor="w")
e_user = ttk.Entry(m, width=40)
e_user.pack(fill="x", pady=(0, 8))
e_user.focus()

ttk.Label(m, text="Password:").pack(anchor="w")
e_pw = ttk.Entry(m, width=40, show="•")
e_pw.pack(fill="x", pady=(0, 8))

ttk.Button(m, text="Guardar", command=save).pack(pady=10, ipadx=20)

root.mainloop()
